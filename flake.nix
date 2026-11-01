{
  description = "myaristotle - Aristotle task watcher and queue runner";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              uv
              python314
              git
            ];

            shellHook = ''
              echo "myaristotle development environment"
              echo "Python: $(python --version)"
              echo "uv: $(uv --version)"
            '';
          };
        }
      );
    };

}
