{
  description = "Isolated GTK4 Layer Shell runtime for Filedrop";

  inputs.nixpkgs.url = "nixpkgs";

  outputs = { nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
    in
    {
      devShells = nixpkgs.lib.genAttrs systems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          giTypelibPackages = [
            pkgs.gtk4.out
            pkgs.gtk4-layer-shell.out
            pkgs.pango.out
            pkgs.harfbuzz.out
            pkgs.graphene.out
            pkgs.glib.out
            pkgs.gdk-pixbuf.out
            pkgs.cairo.out
            pkgs.gobject-introspection.out
          ];
          giTypelibPath = pkgs.lib.makeSearchPathOutput
            "out"
            "lib/girepository-1.0"
            giTypelibPackages;
          sharedLibraryPath = pkgs.lib.makeLibraryPath giTypelibPackages;
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python3
              pkgs.python3Packages.pygobject3
              pkgs.gtk4
              pkgs.gtk4-layer-shell
              pkgs.gobject-introspection
              pkgs.graphene
            ];
            shellHook = ''
              export GI_TYPELIB_PATH="${giTypelibPath}"
              export LD_LIBRARY_PATH="${sharedLibraryPath}"
            '';
          };
        });
    };
}
