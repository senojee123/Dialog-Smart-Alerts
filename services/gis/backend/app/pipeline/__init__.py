"""Reference data pipeline: extract, transform and check Sri Lankan reference geodata, and build releases.

The pipeline turns source files (agency deliveries, OpenStreetMap extracts, open datasets) into a
reference data release in PostGIS, repeatably::

    acquire   fetch or locate each source file, verify its checksum, record where and when it came from
    stage     GDAL/ogr2ogr converts it to a staging GeoPackage in EPSG:4326, with the coordinate operation
              chosen and recorded by pyproj (never guessed: a file without a CRS needs a declared one)
    transform GeoPandas/Shapely map the source attributes to the layer schema (field mappings for agency
              data, tag rules for OpenStreetMap), select the area, and write GIS-ready GeoJSON
    check     file-level QA (CRS, validity, duplicates, identifiers, outliers, extent, counts) in GeoPandas
    load      the loader (app.services.reference_loader) writes the files into a draft release with their
              lineage and QA reports
    verify    database QA in PostGIS (app.services.reference_qa): ST_IsValid, topology, licences, ...
    publish   only a release that passed QA is published; only a production release can be current in
              production
    basemap   GDAL writes PMTiles vector tiles from the same sources, with a MapLibre style, recorded as
              release artifacts

What to build comes from a *profile* (TOML, ``data/pipeline/profiles``): the sources with their licences
(nothing is assumed), the datasets and how each is derived, the areas, and the QA expectations. The
development profile uses openly licensed data and labelled placeholders; production profiles name the
agency datasets and must carry an approved licence review for each source.

GDAL (``ogr2ogr``, ``ogrinfo``) and the Python packages GeoPandas, pyogrio, Shapely and pyproj are needed
(``pip install -e .[pipeline]`` and ``gdal-bin``, or the ``pipeline`` Docker target). The API itself does
not depend on them.
"""
