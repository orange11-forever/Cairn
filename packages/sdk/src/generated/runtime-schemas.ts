// Generated from FastAPI OpenAPI by scripts/generate-sdk.mjs. Do not edit.
export const componentSchemas = {
  "ApiVersionResponse": {
    "properties": {
      "service": {
        "const": "cairn-api",
        "default": "cairn-api",
        "title": "Service",
        "type": "string"
      },
      "version": {
        "const": "v1",
        "default": "v1",
        "title": "Version",
        "type": "string"
      }
    },
    "title": "ApiVersionResponse",
    "type": "object"
  },
  "ErrorBody": {
    "properties": {
      "code": {
        "title": "Code",
        "type": "string"
      },
      "message": {
        "title": "Message",
        "type": "string"
      },
      "traceId": {
        "title": "Traceid",
        "type": "string"
      }
    },
    "required": [
      "message",
      "code",
      "traceId"
    ],
    "title": "ErrorBody",
    "type": "object"
  },
  "HTTPValidationError": {
    "properties": {
      "detail": {
        "items": {
          "$ref": "#/components/schemas/ValidationError"
        },
        "title": "Detail",
        "type": "array"
      }
    },
    "title": "HTTPValidationError",
    "type": "object"
  },
  "HealthResponse": {
    "properties": {
      "service": {
        "const": "cairn-api",
        "default": "cairn-api",
        "title": "Service",
        "type": "string"
      },
      "status": {
        "const": "ok",
        "default": "ok",
        "title": "Status",
        "type": "string"
      },
      "version": {
        "title": "Version",
        "type": "string"
      }
    },
    "required": [
      "version"
    ],
    "title": "HealthResponse",
    "type": "object"
  },
  "IdentityContextResponse": {
    "properties": {
      "csrfToken": {
        "title": "Csrftoken",
        "type": "string"
      },
      "membership": {
        "$ref": "#/components/schemas/MembershipResponse"
      },
      "organization": {
        "$ref": "#/components/schemas/OrganizationResponse"
      },
      "user": {
        "$ref": "#/components/schemas/UserResponse"
      }
    },
    "required": [
      "user",
      "organization",
      "membership",
      "csrfToken"
    ],
    "title": "IdentityContextResponse",
    "type": "object"
  },
  "LoginRequest": {
    "properties": {
      "email": {
        "format": "email",
        "title": "Email",
        "type": "string"
      },
      "password": {
        "minLength": 1,
        "title": "Password",
        "type": "string"
      }
    },
    "required": [
      "email",
      "password"
    ],
    "title": "LoginRequest",
    "type": "object"
  },
  "MembershipResponse": {
    "properties": {
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "role": {
        "title": "Role",
        "type": "string"
      }
    },
    "required": [
      "id",
      "role"
    ],
    "title": "MembershipResponse",
    "type": "object"
  },
  "OrganizationResponse": {
    "properties": {
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "name": {
        "title": "Name",
        "type": "string"
      },
      "slug": {
        "title": "Slug",
        "type": "string"
      }
    },
    "required": [
      "id",
      "slug",
      "name"
    ],
    "title": "OrganizationResponse",
    "type": "object"
  },
  "ReadyResponse": {
    "properties": {
      "status": {
        "const": "ready",
        "default": "ready",
        "title": "Status",
        "type": "string"
      }
    },
    "title": "ReadyResponse",
    "type": "object"
  },
  "UserResponse": {
    "properties": {
      "displayName": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Displayname"
      },
      "email": {
        "title": "Email",
        "type": "string"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      }
    },
    "required": [
      "id",
      "email",
      "displayName"
    ],
    "title": "UserResponse",
    "type": "object"
  },
  "ValidationError": {
    "properties": {
      "ctx": {
        "title": "Context",
        "type": "object"
      },
      "input": {
        "title": "Input"
      },
      "loc": {
        "items": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "integer"
            }
          ]
        },
        "title": "Location",
        "type": "array"
      },
      "msg": {
        "title": "Message",
        "type": "string"
      },
      "type": {
        "title": "Error Type",
        "type": "string"
      }
    },
    "required": [
      "loc",
      "msg",
      "type"
    ],
    "title": "ValidationError",
    "type": "object"
  }
} as const;
