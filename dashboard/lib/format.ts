export function formatDateTime(value: string | undefined): string {
  if (!value) {
    return "n/a";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatRelativeCount(numerator: number, denominator: number): string {
  if (!denominator) {
    return "0 / 0";
  }
  return `${numerator} / ${denominator}`;
}

export function formatScore(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) {
    return "0.00";
  }
  return value.toFixed(2);
}

export function formatPercent(value: number): string {
  return `${value.toFixed(0)}%`;
}

export function shortId(value: string | undefined, size = 8): string {
  if (!value) {
    return "n/a";
  }
  return value.length <= size ? value : value.slice(0, size);
}