# Build integration

Keep generated Soong prebuilt declarations, component-specific integration
patches and system-tool adapters here. No adapters are active yet.

Prefer supported source/prebuilt selection in upstream Soong. Where a project
must be replaced, use a local manifest to check out its wrapper at the same
path. Preserve the module interface, required variants, headers, licenses and
generated inputs. A matching checkout path alone does not replace build rules.

Keep source fallback available when an artifact is absent or its inputs differ.
Do not enable a system-tool replacement solely because an executable exists;
establish its version, behavior and compatibility with the selected build.
