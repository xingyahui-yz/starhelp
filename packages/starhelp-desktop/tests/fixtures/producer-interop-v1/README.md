# Synthetic producer interoperability fixture

These fixture files are copied from the versioned A/B delivery used for the C 0.3.0 producer
replay. They contain only `fixture:` identifiers and synthetic data; the public key is test-only.

- A producer source commit: `00d4a5844e74050359227c274de712878bf9187c`
- A artifact delivery commit: `31e2665cfb9ce1100856d72ebca086b39a603ee8`
- A bundle SHA-256: `cd848169254d78586d9ae197f944688463fb72a513d2b38aba7e888feed4d13b`
- B snapshot serializer commit/profile: `045965bce4fbc38a3baa79b594535c9dd983d776` /
  `starhelp.desktop.snapshot.045965b`
- B snapshot SHA-256: `a0c9fd982bd78e11e2ead2460b08b4ed13b4cb52afbe7f9274a6ecd35bd0cbd5`
- Public key SHA-256: `7fe277b94d7e7d57dd3fceeaad77495fdff04861c02c3b1cc624c736aac8a29e`

The current desktop snapshot serializer round-trips this B snapshot shape. C accepts the signed A
bundle and returns two synthetic plans through the desktop subprocess protocol. This fixture proves
artifact compatibility only; its key and content are not suitable for real public data.
