import type { CSSProperties } from "react";

const paths = {
  plus: "M12 5v14M5 12h14",
  search: "m21 21-5-5M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z",
  chat: "M21 11a9 9 0 0 1-9 9H4l-3 2 2-6a9 9 0 1 1 18-5Z",
  music:
    "M9 18V5l12-3v13M9 6l12-3M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3Zm12-3a3 3 0 1 1-3-3 3 3 0 0 1 3 3Z",
  memory: "M9 3H5v4M15 3h4v4M9 21H5v-4M15 21h4v-4M8 8h8v8H8Z",
  grid: "M3 3h7v7H3ZM14 3h7v7h-7ZM3 14h7v7H3ZM14 14h7v7h-7Z",
  settings:
    "M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  arrow: "M12 20V4m-7 7 7-7 7 7",
  play: "m8 4 12 8-12 8Z",
  pause: "M8 4v16M16 4v16",
  next: "m4 5 11 7-11 7ZM20 5v14",
  previous: "m20 5-11 7 11 7ZM4 5v14",
  volume: "M11 4 5 9H2v6h3l6 5ZM16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14",
  close: "m6 6 12 12M6 18 18 6",
  stop: "M5 5h14v14H5Z",
  queue: "M3 6h18M3 12h14M3 18h9",
  collapse: "M3 3h18v18H3ZM8 3v18",
  check: "m4 12 5 5L20 6",
  up: "m6 15 6-6 6 6",
  down: "m6 9 6 6 6-6",
  link: "M10 14 14 10m-7 7-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2 0 1-1a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0",
};
export type IconName = keyof typeof paths;
export function Icon({
  name,
  size = 18,
  style,
}: {
  name: IconName;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
    >
      <path d={paths[name]} />
    </svg>
  );
}
