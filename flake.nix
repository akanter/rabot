{
  description = "rabot - notify via Signal when RA resale tickets appear";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" "x86_64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
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
          options.services.rabot = {
            enable = lib.mkEnableOption "rabot RA resale ticket watcher";
            eventUrl = lib.mkOption { type = lib.types.str; };
            signalSender = lib.mkOption { type = lib.types.str; };
            signalRecipient = lib.mkOption { type = lib.types.str; };
            interval = lib.mkOption { type = lib.types.str; default = "60s"; };
            cooldownSeconds = lib.mkOption { type = lib.types.int; default = 900; };
            failureThreshold = lib.mkOption { type = lib.types.int; default = 5; };
          };
          config = lib.mkIf cfg.enable {
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
                  "RABOT_SIGNAL_RECIPIENT=${cfg.signalRecipient}"
                  "RABOT_STATE_PATH=/var/lib/rabot/state.json"
                  "RABOT_COOLDOWN_SECONDS=${toString cfg.cooldownSeconds}"
                  "RABOT_FAILURE_THRESHOLD=${toString cfg.failureThreshold}"
                  "HOME=/var/lib/rabot"
                ];
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
    };
}
