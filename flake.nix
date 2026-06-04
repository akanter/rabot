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
        eventUrl = lib.mkOption {
          type = lib.types.str;
          description = "RA event URL to watch, e.g. https://ra.co/events/1234567";
        };
        signalSender = lib.mkOption {
          type = lib.types.str;
          description = "Linked signal-cli account phone number (the sender).";
        };
        signalRecipient = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Recipient phone number. Set this or signalGroupId (or both).";
        };
        signalGroupId = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Signal group ID (base64) to alert. Set this or signalRecipient.";
        };
        cooldownSeconds = lib.mkOption { type = lib.types.int; default = 900; };
        failureThreshold = lib.mkOption { type = lib.types.int; default = 5; };
      } // extra;
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

      nixosModules.default = { config, lib, pkgs, ... }:
        let cfg = config.services.rabot;
        in {
          options.services.rabot = rabotOptions lib {
            interval = lib.mkOption { type = lib.types.str; default = "60s"; };
          };
          config = lib.mkIf cfg.enable {
            assertions = [{
              assertion = cfg.signalRecipient != null || cfg.signalGroupId != null;
              message = "services.rabot: set signalRecipient or signalGroupId (or both).";
            }];
            systemd.services.rabot = {
              description = "rabot RA resale check";
              path = [ pkgs.signal-cli ];
              serviceConfig = {
                Type = "oneshot";
                DynamicUser = true;
                StateDirectory = "rabot";
                ExecStart = "${self.packages.${pkgs.system}.default}/bin/rabot check";
                Environment = [
                  "RABOT_EVENT_URL=${cfg.eventUrl}"
                  "RABOT_SIGNAL_SENDER=${cfg.signalSender}"
                  "RABOT_STATE_PATH=/var/lib/rabot/state.json"
                  "RABOT_COOLDOWN_SECONDS=${toString cfg.cooldownSeconds}"
                  "RABOT_FAILURE_THRESHOLD=${toString cfg.failureThreshold}"
                  "HOME=/var/lib/rabot"
                ]
                ++ lib.optional (cfg.signalRecipient != null) "RABOT_SIGNAL_RECIPIENT=${cfg.signalRecipient}"
                ++ lib.optional (cfg.signalGroupId != null) "RABOT_SIGNAL_GROUP_ID=${cfg.signalGroupId}";
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
          };
        };

      # nix-darwin module: a per-user LaunchAgent (runs as the logged-in user, so
      # $HOME is set and signal-cli's linked data under ~/.local/share is found).
      # rabot's state file defaults to ~/.local/state/rabot/state.json.
      darwinModules.default = { config, lib, pkgs, ... }:
        let cfg = config.services.rabot;
        in {
          options.services.rabot = rabotOptions lib {
            intervalSeconds = lib.mkOption { type = lib.types.int; default = 60; };
          };
          config = lib.mkIf cfg.enable {
            assertions = [{
              assertion = cfg.signalRecipient != null || cfg.signalGroupId != null;
              message = "services.rabot: set signalRecipient or signalGroupId (or both).";
            }];
            launchd.agents.rabot = {
              serviceConfig = {
                ProgramArguments = [ "${self.packages.${pkgs.system}.default}/bin/rabot" "check" ];
                StartInterval = cfg.intervalSeconds;
                RunAtLoad = true;
                StandardErrorPath = "/tmp/rabot.err.log";
                StandardOutPath = "/tmp/rabot.out.log";
                EnvironmentVariables = {
                  RABOT_EVENT_URL = cfg.eventUrl;
                  RABOT_SIGNAL_SENDER = cfg.signalSender;
                  RABOT_COOLDOWN_SECONDS = toString cfg.cooldownSeconds;
                  RABOT_FAILURE_THRESHOLD = toString cfg.failureThreshold;
                } // lib.optionalAttrs (cfg.signalRecipient != null) {
                  RABOT_SIGNAL_RECIPIENT = cfg.signalRecipient;
                } // lib.optionalAttrs (cfg.signalGroupId != null) {
                  RABOT_SIGNAL_GROUP_ID = cfg.signalGroupId;
                };
              };
            };
          };
        };
    };
}
