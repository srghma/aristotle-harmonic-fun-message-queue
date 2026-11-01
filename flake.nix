{
  description = "myaristotle - Aristotle task watcher and queue runner";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
    };

  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      forAllSystems = nixpkgs.lib.genAttrs systems;

      pythonSets = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python314;

          workspace = uv2nix.lib.workspace.loadWorkspace {
            workspaceRoot = ./.;
          };

          overlay = workspace.mkPyprojectOverlay {
            sourcePreference = "wheel";
          };

          pythonBase = pkgs.callPackage pyproject-nix.build.packages {
            inherit python;
          };

          pythonSet = pythonBase.overrideScope (
            nixpkgs.lib.composeManyExtensions [
              pyproject-build-systems.overlays.wheel
              overlay

              (final: prev: {
                myaristotle = prev.myaristotle.overrideAttrs (old: {
                  nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
                    final.editables
                  ];
                });
              })
            ]
          );
        in
        {
          inherit
            pkgs
            python
            workspace
            pythonSet
            ;
        }
      );
    in
    {
      packages = forAllSystems (
        system:
        let
          inherit (pythonSets.${system}) pkgs workspace pythonSet;

          mkApplication = (pkgs.callPackages pyproject-nix.build.util { }).mkApplication;
        in
        {
          default = mkApplication {
            venv = pythonSet.mkVirtualEnv "myaristotle-env" workspace.deps.default;

            package = pythonSet.myaristotle;
          };

          myaristotle = self.packages.${system}.default;
        }
      );

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/myaristotle";
        };
      });

      devShells = forAllSystems (
        system:
        let
          inherit (pythonSets.${system})
            pkgs
            python
            workspace
            pythonSet
            ;

          editableOverlay = workspace.mkEditablePyprojectOverlay {
            root = "$REPO_ROOT";
          };

          editablePythonSet = pythonSet.overrideScope editableOverlay;

          virtualenv = editablePythonSet.mkVirtualEnv "myaristotle-dev-env" workspace.deps.all;
        in
        {
          default = pkgs.mkShell {
            packages = [
              virtualenv
              pkgs.uv
              pkgs.git
            ];

            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT="$(git rev-parse --show-toplevel)"
              echo "myaristotle development environment"
            '';
          };
        }
      );
    };

}
