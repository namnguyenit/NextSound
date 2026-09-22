# NextSound bundled runtime — amd64

Target: Ubuntu 22.04, PipeWire 0.3.48 ABI, WirePlumber 0.4.

## Provenance

- PipeWire 0.3.48 commit `6c4d3a51583f823b789b0de2df1e36d6c2f8dff8`.
- PipeWire 1.6.0 reference commit `700cea78dbe7564131d51b21a7795e2567ee048a`.
- `hegdi/libldacdec` commit `7f3bd6cc1586b764b02f2e4f20b16c7ff18758b9`.
- FDK AAC 2.0.2 from Ubuntu 22.04 Multiverse.
- Patch set stored in the repository `patches/` directory.
- Build commands are documented in `scripts/install-aac-user.sh` and `scripts/install-ldac-user.sh`.

## SHA-256

```text
624d195d48aa4b02f7d48890ab09446e1495896365affe7f88c2f91b9d004e0f  spa-0.2/bluez5/libspa-bluez5.so
27094321124d6830bd6465a3c2d46671cbdc2722f0ac7faf52ce1ef1188224bf  spa-0.2/bluez5/libspa-codec-bluez5-aac.so
8ee9bc3f297eed8226ad9053fda4da9cc965460f8f7ad7ed148492f3d416bfc4  spa-0.2/bluez5/libspa-codec-bluez5-ldac.so
d5224b4611f30876f07bfdc29d6a401310eff118768acbafc097d2fc3d4faa57  lib/libfdk-aac.so.2
c56b74c96e58d5035ee020427f64ca4c0b5b1f362e6469d926a4d13aad10c1d8  lib/libldacBT_abr.so.2
1ff1f5c1e9a278f919da34a5edb1458c7e254884d079b31a1bf1b7dbf60255c7  lib/libldacBT_dec.so.0
2472a51387466f241d22f88d992bdd2ec6827a50dd50f9cf939c2e45eecf7182  lib/libldacBT_enc.so.2
```
