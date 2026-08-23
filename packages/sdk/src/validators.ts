import { componentSchemas } from "./generated/runtime-schemas.ts";
import type { components } from "./generated/schema.d.ts";

type ComponentName = keyof components["schemas"];
type JsonObject = Record<string, unknown>;

function objectValue(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

function referencedSchema(reference: unknown): unknown {
  if (typeof reference !== "string") return undefined;
  const prefix = "#/components/schemas/";
  if (!reference.startsWith(prefix)) return undefined;
  const name = reference.slice(prefix.length);
  return (componentSchemas as unknown as JsonObject)[name];
}

function isUtcMonthEndLeapSecond(value: string): boolean {
  // Validate RFC3339 placement without hard-coding the IERS table, so future
  // announced leap seconds do not require an SDK release.
  const normalized = value
    .replace(/:60(?=(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$)/, ":59")
    .replace("t", "T")
    .replace(/z$/, "Z");
  const timestamp = Date.parse(normalized);
  if (Number.isNaN(timestamp)) return false;

  const instant = new Date(timestamp);
  const followingSecond = new Date(timestamp + 1_000);
  return instant.getUTCHours() === 23 &&
    instant.getUTCMinutes() === 59 &&
    instant.getUTCSeconds() === 59 &&
    followingSecond.getUTCDate() === 1 &&
    followingSecond.getUTCHours() === 0 &&
    followingSecond.getUTCMinutes() === 0 &&
    followingSecond.getUTCSeconds() === 0;
}

function matchesDateTime(value: string): boolean {
  const match = /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])[Tt]([01]\d|2[0-3]):([0-5]\d):([0-5]\d|60)(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(
    value,
  );
  if (match === null) return false;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (day > (daysInMonth[month - 1] ?? 0)) return false;
  return match[6] !== "60" || isUtcMonthEndLeapSecond(value);
}

function matchesStringFormat(format: unknown, value: string): boolean {
  if (format === "uuid") {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    );
  }
  if (format === "email") return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  if (format === "date-time") return matchesDateTime(value);
  return true;
}

function matchesSchema(schema: unknown, value: unknown): boolean {
  const definition = objectValue(schema);
  if (definition === null) return false;

  if ("$ref" in definition) {
    const referenced = referencedSchema(definition.$ref);
    return referenced !== undefined && matchesSchema(referenced, value);
  }
  if (Array.isArray(definition.anyOf)) {
    return definition.anyOf.some((candidate) => matchesSchema(candidate, value));
  }
  if (Array.isArray(definition.oneOf)) {
    return definition.oneOf.filter((candidate) => matchesSchema(candidate, value)).length === 1;
  }
  if (Array.isArray(definition.allOf)) {
    return definition.allOf.every((candidate) => matchesSchema(candidate, value));
  }
  if (Array.isArray(definition.enum) && !definition.enum.some((entry) => Object.is(entry, value))) {
    return false;
  }
  if ("const" in definition && !Object.is(definition.const, value)) return false;

  switch (definition.type) {
    case "null":
      return value === null;
    case "boolean":
      return typeof value === "boolean";
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "string": {
      if (typeof value !== "string") return false;
      if (typeof definition.minLength === "number" && value.length < definition.minLength) {
        return false;
      }
      if (typeof definition.maxLength === "number" && value.length > definition.maxLength) {
        return false;
      }
      return matchesStringFormat(definition.format, value);
    }
    case "array":
      return (
        Array.isArray(value) &&
        (definition.items === undefined ||
          value.every((entry) => matchesSchema(definition.items, entry)))
      );
    case "object": {
      const record = objectValue(value);
      if (record === null) return false;
      const properties = objectValue(definition.properties) ?? {};
      const required = Array.isArray(definition.required)
        ? definition.required.filter((name): name is string => typeof name === "string")
        : [];
      if (!required.every((name) => Object.hasOwn(record, name))) return false;
      for (const [name, propertySchema] of Object.entries(properties)) {
        if (Object.hasOwn(record, name) && !matchesSchema(propertySchema, record[name])) {
          return false;
        }
      }
      if (
        definition.additionalProperties === false &&
        Object.keys(record).some((name) => !Object.hasOwn(properties, name))
      ) {
        return false;
      }
      return true;
    }
    default:
      return false;
  }
}

export function matchesComponentSchema<Name extends ComponentName>(
  name: Name,
  value: unknown,
): value is components["schemas"][Name] {
  return matchesSchema(componentSchemas[name], value);
}
