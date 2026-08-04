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

function matchesStringFormat(format: unknown, value: string): boolean {
  if (format === "uuid") {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    );
  }
  if (format === "email") return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
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
