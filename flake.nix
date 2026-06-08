{
  description = "rabot - notify via Signal when RA resale tickets appear";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" "x86_64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});

      # Options shared by the NixOS (systemd) and nix-darwin (launchd) modules.
      # `extra` lets each platform add its own scheduling option.
      rabotOptions = lib: extra: {
        enable = lib.mkEnableOption "rabot RA resale ticket watcher";
        events = lib.mkOption {
          default = [ ];
          description = ''
            Events to watch, each with an optional own recipient/groupId. A target
            omitted here falls back to the default signalRecipient/signalGroupId.
          '';
          type = lib.types.listOf (lib.types.submodule {
            options = {
              url = lib.mkOption { type = lib.types.str; };
              recipient = lib.mkOption { type = lib.types.nullOr lib.types.str; default = null; };
              groupId = lib.mkOption { type = lib.types.nullOr lib.types.str; default = null; };
            };
          });
        };
        signalSender = lib.mkOption {
          type = lib.types.str;
          description = "Linked signal-cli account phone number (the sender).";
        };
        signalRecipient = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Default recipient phone number (per-event target falls back to this).";
        };
        signalGroupId = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Default Signal group id (per-event target falls back to this).";
        };
        cooldownSeconds = lib.mkOption { type = lib.types.int; default = 900; };
        failureThreshold = lib.mkOption { type = lib.types.int; default = 5; };
        withCliTools = lib.mkOption {
          type = lib.types.bool;
          default = true;
          description = ''
            Install signal-cli and qrencode into system packages, so the one-time
            `signal-cli link` (and rendering its QR) works without `nix run`. The
            signal-cli here matches the one the service uses.
          '';
        };
      } // extra;

      # The rabot config as an attrset; each module renders it to a TOML file and
      # points RABOT_CONFIG at it (one env var instead of a pile). Per-event
      # targets fall back to the default signal_recipient/signal_group_id.
      rabotConfigAttrs = cfg:
        {
          signal_sender = cfg.signalSender;
          cooldown_seconds = cfg.cooldownSeconds;
          failure_threshold = cfg.failureThreshold;
          events = map
            (e: { url = e.url; }
              // nixpkgs.lib.optionalAttrs (e.recipient != null) { recipient = e.recipient; }
              // nixpkgs.lib.optionalAttrs (e.groupId != null) { group = e.groupId; })
            cfg.events;
        }
        // nixpkgs.lib.optionalAttrs (cfg.signalRecipient != null) { signal_recipient = cfg.signalRecipient; }
        // nixpkgs.lib.optionalAttrs (cfg.signalGroupId != null) { signal_group_id = cfg.signalGroupId; };

      # Assertions shared by both modules.
      rabotAssertions = cfg: [
        {
          assertion = cfg.events != [ ];
          message = "services.rabot: set at least one event in `events`.";
        }
        {
          assertion = builtins.all
            (e: e.recipient != null || e.groupId != null
              || cfg.signalRecipient != null || cfg.signalGroupId != null)
            cfg.events;
          message = "services.rabot: every event needs a recipient/groupId, or set a default signalRecipient/signalGroupId.";
        }
      ];
    in
    {
      packages = forAll (pkgs: {
        default = pkgs.python312Packages.buildPythonApplication {
          pname = "rabot";
          version = "0.1.0";
          src = ./.;
          format = "pyproject";
          nativeBuildInputs = [ pkgs.python312Packages.setuptools ];
          propagatedBuildInputs = [ pkgs.python312Packages.httpx ];
          nativeCheckInputs = [ pkgs.python312Packages.pytest pkgs.python312Packages.pytestCheckHook ];
          pythonImportsCheck = [ "rabot" ];
          # Bundle the JVM signal-cli from nixpkgs and make it the default the CLI
          # shells out to. This avoids Homebrew's GraalVM native-image build, which
          # has a reflection bug (IdentityKeyDeserializer) that breaks sends.
          # An explicit RABOT_SIGNAL_CLI in the environment still overrides this.
          makeWrapperArgs = [
            "--set-default" "RABOT_SIGNAL_CLI" "${pkgs.signal-cli}/bin/signal-cli"
          ];
        };
      });

      apps = forAll (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.system}.default}/bin/rabot";
        };
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python312.withPackages (ps: [ ps.httpx ps.pytest ]))
            pkgs.signal-cli
          ];
        };
      });

      # NixOS module: a systemd oneshot + timer, run as a real `user` (NOT
      # DynamicUser) so signal-cli's linked data persists in that user's home and
      # can be linked once interactively. HOME is taken from the user's account so
      # signal-cli (~/.local/share) and rabot state (~/.local/state) resolve there.
      nixosModules.default = { config, lib, pkgs, ... }:
        let cfg = config.services.rabot;
        in {
          options.services.rabot = rabotOptions lib {
            interval = lib.mkOption { type = lib.types.str; default = "60s"; };
            receiveInterval = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = "6h";
              description = ''
                How often to run `signal-cli receive` (systemd time span) to keep the
                linked device healthy (prekeys, group state). null disables it.
              '';
            };
            user = lib.mkOption {
              type = lib.types.str;
              description = "User to run the service as (must have signal-cli linked in their home).";
            };
          };
          config = lib.mkIf cfg.enable {
            assertions = rabotAssertions cfg;
            environment.systemPackages =
              [ self.packages.${pkgs.system}.default ]
              ++ lib.optionals cfg.withCliTools [ pkgs.signal-cli pkgs.qrencode ];
            # After a rebuild, nudge the operator if signal-cli isn't linked yet.
            system.activationScripts.rabot-link-hint.text = ''
              if [ ! -d "${config.users.users.${cfg.user}.home}/.local/share/signal-cli" ]; then
                echo "⚠ rabot: Signal not linked yet — run 'rabot link' as ${cfg.user} to enable alerts." >&2
              fi
            '';
            systemd.services.rabot = {
              description = "rabot RA resale check";
              path = [ pkgs.signal-cli ];
              environment = {
                RABOT_CONFIG = "${(pkgs.formats.toml { }).generate "rabot-config.toml" (rabotConfigAttrs cfg)}";
                HOME = config.users.users.${cfg.user}.home;
              };
              serviceConfig = {
                Type = "oneshot";
                User = cfg.user;
                ExecStart = "${self.packages.${pkgs.system}.default}/bin/rabot check";
              };
            };
            systemd.timers.rabot = {
              wantedBy = [ "timers.target" ];
              timerConfig = {
                OnBootSec = cfg.interval;
                OnUnitActiveSec = cfg.interval;
                RandomizedDelaySec = "15s";
              };
            };
            # Periodic `signal-cli receive` keeps the linked device healthy
            # (refreshes prekeys, group/session state). rabot itself never receives.
            systemd.services.rabot-receive = lib.mkIf (cfg.receiveInterval != null) {
              description = "rabot signal-cli receive (account housekeeping)";
              serviceConfig = {
                Type = "oneshot";
                User = cfg.user;
                Environment = [ "HOME=${config.users.users.${cfg.user}.home}" ];
                ExecStart =
                  "${pkgs.signal-cli}/bin/signal-cli -u ${cfg.signalSender} receive --timeout 10";
                # Discard received-message output (housekeeping only; also avoids
                # logging message contents). Errors still go to the journal.
                StandardOutput = "null";
              };
            };
            systemd.timers.rabot-receive = lib.mkIf (cfg.receiveInterval != null) {
              wantedBy = [ "timers.target" ];
              timerConfig = {
                OnBootSec = "5min";
                OnUnitActiveSec = cfg.receiveInterval;
                RandomizedDelaySec = "5min";
              };
            };
          };
        };

      # nix-darwin module: a LaunchDaemon that runs as `user` (UserName). A daemon
      # (not an agent) is the right model for `sudo darwin-rebuild`: root manages
      # it, no GUI-login/bootstrap dance, and it runs 24/7 regardless of login.
      # HOME is set explicitly so signal-cli finds its linked data under
      # ~/.local/share and rabot writes state under ~/.local/state.
      darwinModules.default = { config, lib, pkgs, ... }:
        let cfg = config.services.rabot;
        in {
          options.services.rabot = rabotOptions lib {
            intervalSeconds = lib.mkOption { type = lib.types.int; default = 60; };
            receiveIntervalSeconds = lib.mkOption {
              type = lib.types.nullOr lib.types.int;
              default = 21600;  # 6h
              description = ''
                How often (seconds) to run `signal-cli receive` to keep the linked
                device healthy (prekeys, group state). null disables it.
              '';
            };
            user = lib.mkOption {
              type = lib.types.str;
              default = config.system.primaryUser;
              description = "User to run the daemon as (must have signal-cli linked).";
            };
          };
          config = lib.mkIf cfg.enable {
            assertions = rabotAssertions cfg;
            environment.systemPackages =
              [ self.packages.${pkgs.system}.default ]
              ++ lib.optionals cfg.withCliTools [ pkgs.signal-cli pkgs.qrencode ];
            # After a rebuild, nudge the operator if signal-cli isn't linked yet.
            system.activationScripts.postActivation.text = lib.mkAfter ''
              if [ ! -d "/Users/${cfg.user}/.local/share/signal-cli" ]; then
                echo "⚠ rabot: Signal not linked yet — run 'rabot link' as ${cfg.user} to enable alerts." >&2
              fi
            '';
            launchd.daemons.rabot = {
              serviceConfig = {
                ProgramArguments = [ "${self.packages.${pkgs.system}.default}/bin/rabot" "check" ];
                UserName = cfg.user;
                StartInterval = cfg.intervalSeconds;
                RunAtLoad = true;
                StandardErrorPath = "/tmp/rabot.err.log";
                StandardOutPath = "/tmp/rabot.out.log";
                EnvironmentVariables = {
                  RABOT_CONFIG = "${(pkgs.formats.toml { }).generate "rabot-config.toml" (rabotConfigAttrs cfg)}";
                  HOME = "/Users/${cfg.user}";
                };
              };
            };
            # Periodic `signal-cli receive` keeps the linked device healthy
            # (refreshes prekeys, group/session state). rabot itself never receives.
            launchd.daemons.rabot-receive = lib.mkIf (cfg.receiveIntervalSeconds != null) {
              serviceConfig = {
                ProgramArguments = [
                  "${pkgs.signal-cli}/bin/signal-cli" "-u" cfg.signalSender "receive" "--timeout" "10"
                ];
                UserName = cfg.user;
                StartInterval = cfg.receiveIntervalSeconds;
                RunAtLoad = true;
                # Discard received-message output (housekeeping only; also avoids
                # logging message contents). Keep stderr for genuine errors.
                StandardOutPath = "/dev/null";
                StandardErrorPath = "/tmp/rabot-receive.err.log";
                EnvironmentVariables = { HOME = "/Users/${cfg.user}"; };
              };
            };
          };
        };
    };
}
