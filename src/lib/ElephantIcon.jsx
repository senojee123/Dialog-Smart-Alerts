export default function ElephantIcon({ color = 'currentColor', size = 56, style }) {
  return (
    <svg
      width={size}
      height={size * 0.82}
      viewBox="0 0 100 82"
      fill={color}
      style={style}
    >
      {/*
        Road-sign style elephant silhouette, left-facing.
        Ear → body → head → trunk → legs drawn as layered filled shapes
        so they merge into a single solid read-at-a-glance icon.
      */}

      {/* Ear (drawn first, partially behind head) */}
      <ellipse cx="30" cy="20" rx="16" ry="19" />

      {/* Head */}
      <ellipse cx="26" cy="28" rx="14" ry="12" />

      {/* Neck bridge between head and body */}
      <rect x="34" y="22" width="16" height="18" rx="4" />

      {/* Body */}
      <ellipse cx="65" cy="38" rx="26" ry="19" />

      {/* Trunk — hanging down from head */}
      <rect x="12" y="36" width="10" height="24" rx="5" />
      {/* Trunk tip curl */}
      <ellipse cx="17" cy="60" rx="7" ry="5" />

      {/* Legs — 4 pillars below body */}
      <rect x="44" y="53" width="10" height="20" rx="5" />
      <rect x="57" y="53" width="10" height="20" rx="5" />
      <rect x="70" y="53" width="10" height="20" rx="5" />

      {/* Tail */}
      <path
        d="M 91 30 Q 100 26 97 36 Q 94 44 88 40"
        stroke={color}
        strokeWidth="4"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  )
}
