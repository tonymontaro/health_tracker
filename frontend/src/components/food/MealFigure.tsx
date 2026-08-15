const variants = ["garden", "ember", "sunrise", "market"] as const;

function variantFor(seed: string, offset: number): (typeof variants)[number] {
  let hash = 0;
  for (const character of seed) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return variants[(hash + offset) % variants.length]!;
}

export function MealFigure({ seed, offset }: { seed: string; offset: number }) {
  const variant = variantFor(seed, offset);
  return <div className={`meal-figure meal-figure-${variant}`} aria-hidden="true">
    <span className="meal-plate" />
    <i className="meal-food meal-food-a" />
    <i className="meal-food meal-food-b" />
    <i className="meal-food meal-food-c" />
  </div>;
}
