// Two sets that share a photo, for the grouped view's help (webui-spec 7.4): the set of A
// holds A and B, the set of B holds B and C, and A and C do not match. Drawn with the
// theme's tokens, so it follows light and dark mode and both palettes; the outline style
// tells the sets apart without relying on colour.
export function SetsDiagram() {
  return (
    <svg className="sets-diagram" viewBox="0 0 360 170" width="100%" role="img" aria-labelledby="sets-diagram-title sets-diagram-desc">
      <title id="sets-diagram-title">Two sets that share a photo</title>
      <desc id="sets-diagram-desc">The set of A holds A and B. The set of B holds B and C. B is in both sets; A and C don't match each other.</desc>
      <text className="label" x="105" y="20">Set of A</text>
      <text className="label" x="255" y="20">Set of B</text>
      <ellipse className="set-a" cx="135" cy="94" rx="95" ry="62" />
      <ellipse className="set-b" cx="225" cy="94" rx="95" ry="62" />
      {(["A", "B", "C"] as const).map((letter, i) => (
        <g key={letter}>
          <rect className="photo" x={68 + i * 92} y="74" width="40" height="40" rx="6" />
          <text className="letter" x={88 + i * 92} y="94">{letter}</text>
        </g>
      ))}
    </svg>
  );
}
