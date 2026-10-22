import { cn } from "@/lib/utils";

// Leaf outlines in a 100×100 box, tip up, stem at the bottom. Slightly lopsided and left open
// at the tip on purpose, so they read as sketched rather than drawn with a compass.
const SHAPES = {
  broad: [
    "M49 5C77 21 88 57 52 91C17 62 19 27 52 8",
    "M51 97L51 91C50 70 49 40 50 11",
    "M50 72C57 66 65 61 72 57M50 70C42 65 34 61 27 58",
    "M50 52C57 46 65 41 72 37M50 50C42 45 35 41 29 37",
    "M50 33C55 28 60 25 64 22M50 32C45 28 40 25 36 23",
  ],
  slender: [
    "M50 3C65 29 64 63 50 95C35 63 37 30 52 6",
    "M50 99L50 95C50 70 50 40 50 7",
    "M50 74L59 64M50 74L41 64M50 56L58 46M50 56L42 46M50 38L56 30M50 38L44 30",
  ],
  round: [
    "M50 13C83 12 93 52 50 91C8 53 17 15 53 14",
    "M50 98L50 91C49 66 50 40 50 15",
    "M50 74C60 68 70 64 79 60M50 72C40 67 30 63 21 60",
    "M50 52C61 45 71 41 80 38M50 50C39 44 29 40 20 38",
    "M50 32C58 27 65 25 71 24M50 31C42 26 35 25 29 24",
  ],
  sprig: [
    "M30 97C42 74 52 50 72 6",
    "M40 75C24 70 14 58 12 45C27 47 37 58 40 75",
    "M48 55C66 54 79 45 84 32C68 31 55 40 48 55",
    "M57 35C44 27 38 16 39 4C51 10 57 21 57 35",
  ],
} as const;

type Shape = keyof typeof SHAPES;

interface Placement {
  shape: Shape;
  /** Corner anchor and rotation, as Tailwind classes. Each leaf is centered on its corner. */
  className: string;
  /** Seconds before this leaf starts drawing, so they sketch in one after another. */
  delay: number;
}

// One big leaf per corner, centered on the corner so about a quarter shows and the rest runs off
// the edge. Rotations point each leaf's visible part diagonally inward.
const PLACEMENTS: Placement[] = [
  { shape: "broad", className: "left-0 top-0 -translate-x-1/2 -translate-y-1/2 rotate-[140deg]", delay: 0 },
  { shape: "sprig", className: "right-0 top-0 translate-x-1/2 -translate-y-1/2 rotate-[200deg]", delay: 0.3 },
  { shape: "round", className: "left-0 bottom-0 -translate-x-1/2 translate-y-1/2 rotate-[35deg]", delay: 0.6 },
  { shape: "slender", className: "right-0 bottom-0 translate-x-1/2 translate-y-1/2 -rotate-[40deg]", delay: 0.9 },
];

/** Big leaf outlines sketched into the corners of the hero. Purely visual, so hidden from screen readers. */
export function HeroLeaves() {
  return (
    // ink is near-white in dark mode and near-black in light mode, so the outlines show in both.
    <div className="pointer-events-none absolute inset-0 text-ink/35" aria-hidden>
      {PLACEMENTS.map(({ shape, className, delay }) => (
        <svg
          key={shape}
          viewBox="0 0 100 100"
          className={cn("absolute h-auto w-64 sm:w-80 lg:w-[30rem]", className)}
        >
          {SHAPES[shape].map((d) => (
            <path
              key={d}
              d={d}
              pathLength={1}
              className="sketch-path"
              style={{ animationDelay: `${delay}s` }}
              fill="none"
              stroke="currentColor"
              // In viewBox units: about 1–2px at the sizes above. (non-scaling-stroke would keep it
              // constant, but browsers then ignore pathLength and the sketch-in breaks.)
              strokeWidth={0.42}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}
        </svg>
      ))}
    </div>
  );
}
