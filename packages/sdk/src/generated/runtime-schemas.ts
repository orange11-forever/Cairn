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
  "DependencyResponse": {
    "properties": {
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "predecessorTaskId": {
        "format": "uuid",
        "title": "Predecessortaskid",
        "type": "string"
      },
      "successorTaskId": {
        "format": "uuid",
        "title": "Successortaskid",
        "type": "string"
      }
    },
    "required": [
      "id",
      "predecessorTaskId",
      "successorTaskId",
      "createdAt"
    ],
    "title": "DependencyResponse",
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
  "ProjectCreateRequest": {
    "additionalProperties": false,
    "properties": {
      "description": {
        "anyOf": [
          {
            "maxLength": 4000,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Description"
      },
      "name": {
        "maxLength": 160,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      }
    },
    "required": [
      "name"
    ],
    "title": "ProjectCreateRequest",
    "type": "object"
  },
  "ProjectPage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/ProjectResponse"
        },
        "title": "Items",
        "type": "array"
      },
      "nextCursor": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Nextcursor"
      }
    },
    "required": [
      "items",
      "nextCursor"
    ],
    "title": "ProjectPage",
    "type": "object"
  },
  "ProjectResponse": {
    "properties": {
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
      "description": {
        "anyOf": [
          {
            "maxLength": 4000,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Description"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "name": {
        "maxLength": 160,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      },
      "updatedAt": {
        "format": "date-time",
        "title": "Updatedat",
        "type": "string"
      }
    },
    "required": [
      "id",
      "name",
      "description",
      "createdAt",
      "updatedAt"
    ],
    "title": "ProjectResponse",
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
  "TaskCreateRequest": {
    "additionalProperties": false,
    "properties": {
      "acceptanceCriteria": {
        "anyOf": [
          {
            "maxLength": 10000,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Acceptancecriteria"
      },
      "dueAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Dueat"
      },
      "parentTaskId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Parenttaskid"
      },
      "priority": {
        "$ref": "#/components/schemas/TaskPriority",
        "default": "medium"
      },
      "stageId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Stageid"
      },
      "title": {
        "maxLength": 240,
        "minLength": 1,
        "title": "Title",
        "type": "string"
      }
    },
    "required": [
      "title"
    ],
    "title": "TaskCreateRequest",
    "type": "object"
  },
  "TaskDependencyCreateRequest": {
    "additionalProperties": false,
    "properties": {
      "predecessorTaskId": {
        "description": "The predecessor task. The task identified by the route is the successor, forming predecessor -> successor.",
        "format": "uuid",
        "title": "Predecessortaskid",
        "type": "string"
      }
    },
    "required": [
      "predecessorTaskId"
    ],
    "title": "TaskDependencyCreateRequest",
    "type": "object"
  },
  "TaskPage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/TaskResponse"
        },
        "title": "Items",
        "type": "array"
      },
      "nextCursor": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Nextcursor"
      }
    },
    "required": [
      "items",
      "nextCursor"
    ],
    "title": "TaskPage",
    "type": "object"
  },
  "TaskPriority": {
    "enum": [
      "low",
      "medium",
      "high",
      "critical"
    ],
    "title": "TaskPriority",
    "type": "string"
  },
  "TaskResponse": {
    "properties": {
      "acceptanceCriteria": {
        "anyOf": [
          {
            "maxLength": 10000,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Acceptancecriteria"
      },
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
      "dueAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Dueat"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "parentTaskId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Parenttaskid"
      },
      "priority": {
        "$ref": "#/components/schemas/TaskPriority"
      },
      "projectId": {
        "format": "uuid",
        "title": "Projectid",
        "type": "string"
      },
      "stageId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Stageid"
      },
      "status": {
        "$ref": "#/components/schemas/TaskStatus"
      },
      "title": {
        "maxLength": 240,
        "minLength": 1,
        "title": "Title",
        "type": "string"
      },
      "updatedAt": {
        "format": "date-time",
        "title": "Updatedat",
        "type": "string"
      }
    },
    "required": [
      "id",
      "projectId",
      "title",
      "stageId",
      "parentTaskId",
      "status",
      "priority",
      "dueAt",
      "acceptanceCriteria",
      "createdAt",
      "updatedAt"
    ],
    "title": "TaskResponse",
    "type": "object"
  },
  "TaskStatus": {
    "enum": [
      "backlog",
      "todo",
      "in_progress",
      "blocked",
      "done",
      "cancelled"
    ],
    "title": "TaskStatus",
    "type": "string"
  },
  "TaskStatusUpdateRequest": {
    "additionalProperties": false,
    "properties": {
      "status": {
        "$ref": "#/components/schemas/TaskStatus"
      }
    },
    "required": [
      "status"
    ],
    "title": "TaskStatusUpdateRequest",
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
