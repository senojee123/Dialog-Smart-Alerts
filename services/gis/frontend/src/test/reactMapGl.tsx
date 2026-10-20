/**
 * A stand-in for react-map-gl in jsdom, where there is no WebGL.
 *
 * The map, its sources and its layers render as elements a test can find, and the props the map was
 * given are recorded so a test can fire `onClick` or `onLoad` as the map would.
 */
import { Children, cloneElement, isValidElement, type ReactNode } from 'react';

export interface RecordedMapProps {
  readonly interactiveLayerIds?: readonly string[];
  readonly cursor?: string;
  readonly onClick?: (event: unknown) => void;
  readonly onLoad?: (event: unknown) => void;
  readonly onMoveEnd?: (event: unknown) => void;
  readonly onError?: (event: unknown) => void;
  readonly mapStyle?: unknown;
}

export const mapState: {
  props: RecordedMapProps | null;
  sources: { id: string | undefined; cluster: boolean | undefined; data: unknown }[];
  layers: { id: string | undefined; type: string; filter: unknown; source: string | undefined }[];
} = { props: null, sources: [], layers: [] };

export function resetMapState(): void {
  mapState.props = null;
  mapState.sources = [];
  mapState.layers = [];
}

/** The module factory for `vi.mock('react-map-gl/maplibre', ...)`. */
export function mapGlMock() {
  const Map = ({ children, ...props }: RecordedMapProps & { children?: ReactNode }) => {
    mapState.props = props;
    return (
      <div data-testid="map" data-cursor={props.cursor}>
        {children}
      </div>
    );
  };
  const Source = ({
    id,
    children,
    cluster,
    data,
  }: {
    id?: string;
    children?: ReactNode;
    cluster?: boolean;
    data?: unknown;
  }) => {
    mapState.sources.push({ id, cluster, data });
    // As react-map-gl does: each direct child is given the source id (a fragment would swallow it).
    return (
      <div data-testid={`source-${id ?? 'anonymous'}`} data-cluster={cluster === true ? 'yes' : 'no'}>
        {Children.map(children, (child) =>
          isValidElement<{ source?: string | undefined }>(child) ? cloneElement(child, { source: id }) : child,
        )}
      </div>
    );
  };
  const Layer = ({
    id,
    type,
    filter,
    source,
  }: {
    id?: string;
    type: string;
    filter?: unknown;
    source?: string;
  }) => {
    mapState.layers.push({ id, type, filter, source });
    return <div data-testid={`layer-${id ?? 'anonymous'}`} data-layer-type={type} />;
  };
  const Popup = ({ children }: { children?: ReactNode }) => <div data-testid="popup">{children}</div>;
  const nothing = () => null;
  const AttributionControl = ({ customAttribution }: { customAttribution?: string | string[] }) => (
    <div data-testid="attribution">{[customAttribution ?? []].flat().join(' | ')}</div>
  );
  return {
    Map,
    default: Map,
    Source,
    Layer,
    Popup,
    NavigationControl: nothing,
    ScaleControl: nothing,
    AttributionControl,
    useMap: () => ({}),
  };
}
