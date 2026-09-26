// The NegativeSpace mark, from the maintainer's logo.svg: the same three shapes and
// 991:956 proportions, drawn in the text colour (the original is white, which vanishes
// on a light header) so it follows light and dark mode.
export function Logo({ height = 26 }: { height?: number }) {
  return (
    <svg className="logo" viewBox="131 167 991 956" height={height} width={Math.round((height * 991) / 956)}
         aria-hidden="true" focusable="false">
      <g fill="currentColor">
        <path d="M173 183 L470 526 L470 1122 L216 1122 Q131 1122 131 1037 L131 262 Q131 215 173 183 Z" />
        <path d="M599 167 L1027 167 Q1121 167 1121 261 L1121 872 L642 322 L642 216 Z" />
        <path d="M599 702 L964 1122 L599 1122 Z" />
      </g>
    </svg>
  );
}
