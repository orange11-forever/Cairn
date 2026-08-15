// Generated from FastAPI OpenAPI by scripts/generate-sdk.mjs. Do not edit.
export const componentSchemas = {
  "AclEntryResponse": {
    "properties": {
      "grantedAt": {
        "format": "date-time",
        "title": "Grantedat",
        "type": "string"
      },
      "grantedById": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Grantedbyid"
      },
      "grantedByType": {
        "$ref": "#/components/schemas/ActorType"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "permission": {
        "$ref": "#/components/schemas/ProjectPermission"
      },
      "principalId": {
        "title": "Principalid",
        "type": "string"
      },
      "principalType": {
        "$ref": "#/components/schemas/PrincipalType"
      },
      "resourceId": {
        "format": "uuid",
        "title": "Resourceid",
        "type": "string"
      },
      "resourceType": {
        "$ref": "#/components/schemas/ResourceType"
      }
    },
    "required": [
      "id",
      "resourceType",
      "resourceId",
      "principalType",
      "principalId",
      "permission",
      "grantedByType",
      "grantedById",
      "grantedAt"
    ],
    "title": "AclEntryResponse",
    "type": "object"
  },
  "AclGrantRequest": {
    "additionalProperties": false,
    "properties": {
      "permission": {
        "$ref": "#/components/schemas/ProjectPermission"
      }
    },
    "required": [
      "permission"
    ],
    "title": "AclGrantRequest",
    "type": "object"
  },
  "AclPage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/AclEntryResponse"
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
    "title": "AclPage",
    "type": "object"
  },
  "ActorType": {
    "enum": [
      "user",
      "system"
    ],
    "title": "ActorType",
    "type": "string"
  },
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
  "BatchDetailResponse": {
    "properties": {
      "completedAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Completedat"
      },
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
      "failedCount": {
        "title": "Failedcount",
        "type": "integer"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "itemCount": {
        "title": "Itemcount",
        "type": "integer"
      },
      "items": {
        "items": {
          "$ref": "#/components/schemas/IngestionItemResponse"
        },
        "title": "Items",
        "type": "array"
      },
      "readyCount": {
        "title": "Readycount",
        "type": "integer"
      },
      "status": {
        "$ref": "#/components/schemas/IngestionBatchStatus"
      }
    },
    "required": [
      "id",
      "status",
      "itemCount",
      "readyCount",
      "failedCount",
      "createdAt",
      "completedAt",
      "items"
    ],
    "title": "BatchDetailResponse",
    "type": "object"
  },
  "ChunkContextResponse": {
    "properties": {
      "after": {
        "anyOf": [
          {
            "$ref": "#/components/schemas/ChunkResponse"
          },
          {
            "type": "null"
          }
        ]
      },
      "before": {
        "anyOf": [
          {
            "$ref": "#/components/schemas/ChunkResponse"
          },
          {
            "type": "null"
          }
        ]
      },
      "hit": {
        "$ref": "#/components/schemas/ChunkResponse"
      },
      "resourceId": {
        "format": "uuid",
        "title": "Resourceid",
        "type": "string"
      },
      "resourceVersionId": {
        "format": "uuid",
        "title": "Resourceversionid",
        "type": "string"
      }
    },
    "required": [
      "resourceId",
      "resourceVersionId",
      "hit",
      "before",
      "after"
    ],
    "title": "ChunkContextResponse",
    "type": "object"
  },
  "ChunkResponse": {
    "properties": {
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "locator": {
        "discriminator": {
          "mapping": {
            "csv": "#/components/schemas/CsvLocator",
            "docx": "#/components/schemas/DocxLocator",
            "html": "#/components/schemas/HtmlLocator",
            "markdown": "#/components/schemas/TextLocator",
            "pdf": "#/components/schemas/PdfLocator",
            "pptx": "#/components/schemas/PptxLocator",
            "text": "#/components/schemas/TextLocator",
            "xlsx": "#/components/schemas/XlsxLocator"
          },
          "propertyName": "type"
        },
        "oneOf": [
          {
            "$ref": "#/components/schemas/PdfLocator"
          },
          {
            "$ref": "#/components/schemas/DocxLocator"
          },
          {
            "$ref": "#/components/schemas/PptxLocator"
          },
          {
            "$ref": "#/components/schemas/XlsxLocator"
          },
          {
            "$ref": "#/components/schemas/CsvLocator"
          },
          {
            "$ref": "#/components/schemas/HtmlLocator"
          },
          {
            "$ref": "#/components/schemas/TextLocator"
          }
        ],
        "title": "Locator"
      },
      "ordinal": {
        "title": "Ordinal",
        "type": "integer"
      },
      "text": {
        "title": "Text",
        "type": "string"
      }
    },
    "required": [
      "id",
      "ordinal",
      "text",
      "locator"
    ],
    "title": "ChunkResponse",
    "type": "object"
  },
  "CsvLocator": {
    "properties": {
      "rowEnd": {
        "minimum": 1,
        "title": "Rowend",
        "type": "integer"
      },
      "rowStart": {
        "minimum": 1,
        "title": "Rowstart",
        "type": "integer"
      },
      "type": {
        "const": "csv",
        "default": "csv",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "rowStart",
      "rowEnd"
    ],
    "title": "CsvLocator",
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
  "DocxLocator": {
    "properties": {
      "headingPath": {
        "items": {
          "type": "string"
        },
        "title": "Headingpath",
        "type": "array"
      },
      "paragraph": {
        "anyOf": [
          {
            "minimum": 1,
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "title": "Paragraph"
      },
      "table": {
        "anyOf": [
          {
            "minimum": 1,
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "title": "Table"
      },
      "type": {
        "const": "docx",
        "default": "docx",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "headingPath"
    ],
    "title": "DocxLocator",
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
  "HtmlLocator": {
    "properties": {
      "block": {
        "minimum": 1,
        "title": "Block",
        "type": "integer"
      },
      "headingPath": {
        "items": {
          "type": "string"
        },
        "title": "Headingpath",
        "type": "array"
      },
      "type": {
        "const": "html",
        "default": "html",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "headingPath",
      "block"
    ],
    "title": "HtmlLocator",
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
  "IngestionBatchStatus": {
    "enum": [
      "pending",
      "processing",
      "completed",
      "completed_with_errors",
      "failed"
    ],
    "title": "IngestionBatchStatus",
    "type": "string"
  },
  "IngestionItemResponse": {
    "properties": {
      "completedAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Completedat"
      },
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
      "errorCode": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Errorcode"
      },
      "errorDetail": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Errordetail"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "mediaType": {
        "title": "Mediatype",
        "type": "string"
      },
      "normalizedPath": {
        "title": "Normalizedpath",
        "type": "string"
      },
      "parentItemId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Parentitemid"
      },
      "resourceId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Resourceid"
      },
      "resourceVersionId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Resourceversionid"
      },
      "sizeBytes": {
        "title": "Sizebytes",
        "type": "integer"
      },
      "status": {
        "$ref": "#/components/schemas/IngestionItemStatus"
      }
    },
    "required": [
      "id",
      "parentItemId",
      "normalizedPath",
      "mediaType",
      "sizeBytes",
      "status",
      "errorCode",
      "errorDetail",
      "resourceId",
      "resourceVersionId",
      "createdAt",
      "completedAt"
    ],
    "title": "IngestionItemResponse",
    "type": "object"
  },
  "IngestionItemStatus": {
    "enum": [
      "awaiting_upload",
      "queued",
      "processing",
      "ready",
      "failed"
    ],
    "title": "IngestionItemStatus",
    "type": "string"
  },
  "KnowledgeCapabilities": {
    "properties": {
      "canWrite": {
        "title": "Canwrite",
        "type": "boolean"
      }
    },
    "required": [
      "canWrite"
    ],
    "title": "KnowledgeCapabilities",
    "type": "object"
  },
  "KnowledgeResourcePage": {
    "properties": {
      "capabilities": {
        "$ref": "#/components/schemas/KnowledgeCapabilities"
      },
      "items": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeResourceResponse"
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
      "nextCursor",
      "capabilities"
    ],
    "title": "KnowledgeResourcePage",
    "type": "object"
  },
  "KnowledgeResourceResponse": {
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
      "latestVersion": {
        "anyOf": [
          {
            "$ref": "#/components/schemas/KnowledgeVersionResponse"
          },
          {
            "type": "null"
          }
        ]
      },
      "sourceType": {
        "title": "Sourcetype",
        "type": "string"
      },
      "title": {
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
      "title",
      "sourceType",
      "createdAt",
      "updatedAt",
      "latestVersion"
    ],
    "title": "KnowledgeResourceResponse",
    "type": "object"
  },
  "KnowledgeVersionResponse": {
    "properties": {
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
      "errorCode": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Errorcode"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "mediaType": {
        "title": "Mediatype",
        "type": "string"
      },
      "processingStartedAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Processingstartedat"
      },
      "readyAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Readyat"
      },
      "retryable": {
        "default": false,
        "title": "Retryable",
        "type": "boolean"
      },
      "sha256": {
        "title": "Sha256",
        "type": "string"
      },
      "sizeBytes": {
        "title": "Sizebytes",
        "type": "integer"
      },
      "sourceType": {
        "title": "Sourcetype",
        "type": "string"
      },
      "status": {
        "$ref": "#/components/schemas/ResourceVersionStatus"
      }
    },
    "required": [
      "id",
      "sourceType",
      "mediaType",
      "sizeBytes",
      "sha256",
      "status",
      "errorCode",
      "createdAt",
      "processingStartedAt",
      "readyAt"
    ],
    "title": "KnowledgeVersionResponse",
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
  "MembershipDetailResponse": {
    "properties": {
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
      "displayName": {
        "title": "Displayname",
        "type": "string"
      },
      "email": {
        "format": "email",
        "title": "Email",
        "type": "string"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "role": {
        "$ref": "#/components/schemas/MembershipRole"
      },
      "userId": {
        "format": "uuid",
        "title": "Userid",
        "type": "string"
      }
    },
    "required": [
      "id",
      "userId",
      "email",
      "displayName",
      "role",
      "createdAt"
    ],
    "title": "MembershipDetailResponse",
    "type": "object"
  },
  "MembershipPage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/MembershipDetailResponse"
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
    "title": "MembershipPage",
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
        "$ref": "#/components/schemas/MembershipRole"
      }
    },
    "required": [
      "id",
      "role"
    ],
    "title": "MembershipResponse",
    "type": "object"
  },
  "MembershipRole": {
    "enum": [
      "owner",
      "admin",
      "member",
      "viewer"
    ],
    "title": "MembershipRole",
    "type": "string"
  },
  "MembershipRoleUpdateRequest": {
    "additionalProperties": false,
    "properties": {
      "role": {
        "$ref": "#/components/schemas/MembershipRole"
      }
    },
    "required": [
      "role"
    ],
    "title": "MembershipRoleUpdateRequest",
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
  "PdfLocator": {
    "properties": {
      "page": {
        "minimum": 1,
        "title": "Page",
        "type": "integer"
      },
      "type": {
        "const": "pdf",
        "default": "pdf",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "page"
    ],
    "title": "PdfLocator",
    "type": "object"
  },
  "PptxLocator": {
    "properties": {
      "area": {
        "enum": [
          "body",
          "notes"
        ],
        "title": "Area",
        "type": "string"
      },
      "slide": {
        "minimum": 1,
        "title": "Slide",
        "type": "integer"
      },
      "type": {
        "const": "pptx",
        "default": "pptx",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "slide",
      "area"
    ],
    "title": "PptxLocator",
    "type": "object"
  },
  "PrincipalType": {
    "enum": [
      "org",
      "role",
      "user",
      "group"
    ],
    "title": "PrincipalType",
    "type": "string"
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
  "ProjectPermission": {
    "enum": [
      "read",
      "write",
      "manage"
    ],
    "title": "ProjectPermission",
    "type": "string"
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
  "ResourceType": {
    "enum": [
      "project"
    ],
    "title": "ResourceType",
    "type": "string"
  },
  "ResourceVersionStatus": {
    "enum": [
      "queued",
      "processing",
      "ready",
      "failed"
    ],
    "title": "ResourceVersionStatus",
    "type": "string"
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
  "TextLocator": {
    "properties": {
      "headingPath": {
        "items": {
          "type": "string"
        },
        "title": "Headingpath",
        "type": "array"
      },
      "lineEnd": {
        "minimum": 1,
        "title": "Lineend",
        "type": "integer"
      },
      "lineStart": {
        "minimum": 1,
        "title": "Linestart",
        "type": "integer"
      },
      "type": {
        "enum": [
          "text",
          "markdown"
        ],
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "type",
      "lineStart",
      "lineEnd"
    ],
    "title": "TextLocator",
    "type": "object"
  },
  "UploadBatchCreateRequest": {
    "additionalProperties": false,
    "properties": {
      "files": {
        "items": {
          "$ref": "#/components/schemas/UploadFileIntent"
        },
        "maxItems": 20,
        "minItems": 1,
        "title": "Files",
        "type": "array"
      }
    },
    "required": [
      "files"
    ],
    "title": "UploadBatchCreateRequest",
    "type": "object"
  },
  "UploadBatchCreateResponse": {
    "properties": {
      "batchId": {
        "format": "uuid",
        "title": "Batchid",
        "type": "string"
      },
      "uploads": {
        "items": {
          "$ref": "#/components/schemas/UploadInstruction"
        },
        "title": "Uploads",
        "type": "array"
      }
    },
    "required": [
      "batchId",
      "uploads"
    ],
    "title": "UploadBatchCreateResponse",
    "type": "object"
  },
  "UploadCompleteResponse": {
    "properties": {
      "batchId": {
        "format": "uuid",
        "title": "Batchid",
        "type": "string"
      },
      "itemId": {
        "format": "uuid",
        "title": "Itemid",
        "type": "string"
      },
      "resourceId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Resourceid"
      },
      "resourceVersionId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Resourceversionid"
      },
      "status": {
        "$ref": "#/components/schemas/IngestionItemStatus"
      },
      "uploadId": {
        "format": "uuid",
        "title": "Uploadid",
        "type": "string"
      }
    },
    "required": [
      "uploadId",
      "batchId",
      "itemId",
      "resourceId",
      "resourceVersionId",
      "status"
    ],
    "title": "UploadCompleteResponse",
    "type": "object"
  },
  "UploadFileIntent": {
    "additionalProperties": false,
    "properties": {
      "fileName": {
        "maxLength": 255,
        "minLength": 1,
        "title": "Filename",
        "type": "string"
      },
      "mediaType": {
        "maxLength": 127,
        "minLength": 1,
        "title": "Mediatype",
        "type": "string"
      },
      "sha256": {
        "pattern": "^[0-9a-f]{64}$",
        "title": "Sha256",
        "type": "string"
      },
      "sizeBytes": {
        "exclusiveMinimum": 0,
        "title": "Sizebytes",
        "type": "integer"
      }
    },
    "required": [
      "fileName",
      "mediaType",
      "sizeBytes",
      "sha256"
    ],
    "title": "UploadFileIntent",
    "type": "object"
  },
  "UploadInstruction": {
    "properties": {
      "expiresAt": {
        "format": "date-time",
        "title": "Expiresat",
        "type": "string"
      },
      "headers": {
        "additionalProperties": {
          "type": "string"
        },
        "title": "Headers",
        "type": "object"
      },
      "itemId": {
        "format": "uuid",
        "title": "Itemid",
        "type": "string"
      },
      "method": {
        "const": "PUT",
        "default": "PUT",
        "title": "Method",
        "type": "string"
      },
      "uploadId": {
        "format": "uuid",
        "title": "Uploadid",
        "type": "string"
      },
      "url": {
        "title": "Url",
        "type": "string"
      }
    },
    "required": [
      "uploadId",
      "itemId",
      "url",
      "headers",
      "expiresAt"
    ],
    "title": "UploadInstruction",
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
  "XlsxLocator": {
    "properties": {
      "cellRange": {
        "title": "Cellrange",
        "type": "string"
      },
      "sheet": {
        "title": "Sheet",
        "type": "string"
      },
      "type": {
        "const": "xlsx",
        "default": "xlsx",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "sheet",
      "cellRange"
    ],
    "title": "XlsxLocator",
    "type": "object"
  }
} as const;
