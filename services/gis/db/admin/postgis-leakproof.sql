-- Let row-level security use spatial indexes. Run as a superuser in every GIS database:
--
--   psql -U postgres -d gis -f db/admin/postgis-leakproof.sql
--
-- Why: under row-level security, PostgreSQL uses a query condition for an index scan only if its
-- operator is LEAKPROOF (it could otherwise see rows the policy hides). PostGIS does not mark its
-- bounding-box operator (&&) as leakproof, so without this statement every geofence and device lookup
-- reads the whole table. The operator returns only a boolean and cannot fail for the columns of this
-- schema (every geometry column has a fixed SRID), so it reveals nothing about hidden rows.
--
-- db/init/20-gis-roles-and-databases.sh applies it when the database container is initialised.
-- Apply it again after ALTER EXTENSION postgis UPDATE, which recreates the function. The readiness
-- check "tenant_spatial_indexes" warns while it is missing. Managed services without a superuser
-- cannot apply it; the service then still returns correct results, only slower on large tenant tables.

ALTER FUNCTION public.geometry_overlaps(public.geometry, public.geometry) LEAKPROOF;
