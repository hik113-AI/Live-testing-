// api/geo.js — lightweight state classifier for Peninsular Malaysia.
// Not survey-accurate (uses nearest-centroid, not real polygon boundaries),
// but good enough to answer "how many in Selangor / Johor / Penang" style
// questions correctly at the state level. Suburb-level questions (e.g.
// "Bangsar South") are handled separately via name matching in ask.js.

export const STATES = [
  "Perlis", "Kedah", "Penang", "Perak", "Selangor", "Kuala Lumpur",
  "Putrajaya", "Negeri Sembilan", "Melaka", "Johor", "Pahang",
  "Terengganu", "Kelantan"
];

const CENTROIDS = {
  "Perlis":          [6.45, 100.20],
  "Kedah":           [6.05, 100.55],
  "Penang":          [5.35, 100.35],
  "Perak":           [4.70, 101.10],
  "Selangor":        [3.20, 101.35],
  "Kuala Lumpur":    [3.14, 101.69],
  "Putrajaya":       [2.93, 101.69],
  "Negeri Sembilan": [2.75, 102.05],
  "Melaka":          [2.25, 102.25],
  "Johor":           [1.85, 103.35],
  "Pahang":          [3.75, 102.70],
  "Terengganu":      [5.10, 103.05],
  "Kelantan":        [5.80, 102.15]
};

export function nearestState(lat, lon) {
  let best = null, bestDist = Infinity;
  for (const state of STATES) {
    const [cLat, cLon] = CENTROIDS[state];
    const dLat = lat - cLat, dLon = lon - cLon;
    const dist = dLat * dLat + dLon * dLon;
    if (dist < bestDist) { bestDist = dist; best = state; }
  }
  return best;
}
