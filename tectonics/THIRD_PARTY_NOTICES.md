# Third-party material in the tectonics package

## Atlas code

An Atlas code licence has not yet been selected by the owner. This notice is
attribution and inventory, not a new licence grant. A future project licence must
identify its intended code scope and must not overwrite third-party licences.

## PB2002 reference data

The vendored files under `reference_data/pb2002/` contain Peter Bird's PB2002
reference model, published in *An updated digital model of plate boundaries*,
Geochemistry, Geophysics, Geosystems 4(3), 1027 (2003),
DOI: `10.1029/2001GC000252`. They were obtained from the
[fraxen/tectonicplates mirror](https://github.com/fraxen/tectonicplates) at commit
`339b0c56563c118307b1f4542703047f5f698fae`.

The mirror supplies the **Open Data Commons Attribution License v1.0 (ODC-By)**.
Its [licence notice](reference_data/pb2002/LICENSE.md),
[original documentation](reference_data/pb2002/original/README.md) and
[source manifest](reference_data/pb2002/SOURCE_MANIFEST.json) are retained unchanged.
Derived maps must identify PB2002/Bird, the mirror/pin and the data licence; they
must not imply endorsement or replace source discrepancies with repaired data.
The diagnostic visual tool includes this attribution in its output manifest and
on the reference map itself.

## Material knowledge and external software

`earth_material_data.py` and the material-library records retain property sources,
units, original conditions and interpretation limits. Bibliographic citations
are not permission to redistribute entire source publications; this package does
not vendor those publications. Do not reinterpret a property source as a general
hot/high-pressure constitutive law or an independent validation result.

Scientific libraries declared in `pyproject.toml` are installed separately; their
binaries are not bundled in this source delivery. Their own licences continue to
apply. This inventory is not a legal audit of every historical Atlas directory,
which remains outside the isolated tectonics package.

Licensing guidance: [GitHub repository licensing](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).
