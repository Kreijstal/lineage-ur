# Component recipes

Add one directory per component, containing its recipe, component metadata,
patches and validation notes. There are no active recipes yet.

Start from the existing LineageOS implementation. Record its repository and
commit, exact inputs, required variants and dependencies before attempting an
upstream-version substitution. Use `templates/component.json` as a checklist;
replace all placeholders before treating a component as buildable.

Termux/TUR-style `build.sh` recipes are a packaging model. Their builder is not
vendored here, and Android platform libraries may require the platform toolchain
and private headers rather than the stock Termux NDK build environment.
