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
  "AnswerModelOption": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
        "type": "string"
      },
      "model": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Model"
      },
      "name": {
        "title": "Name",
        "type": "string"
      },
      "protocol": {
        "anyOf": [
          {
            "enum": [
              "openai-compatible",
              "openai-responses",
              "anthropic",
              "gemini"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Protocol"
      }
    },
    "required": [
      "id",
      "name",
      "model",
      "protocol"
    ],
    "title": "AnswerModelOption",
    "type": "object"
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
  "AssigneePage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/AssigneeResponse"
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
    "title": "AssigneePage",
    "type": "object"
  },
  "AssigneeResponse": {
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
      "role": {
        "title": "Role",
        "type": "string"
      },
      "userId": {
        "format": "uuid",
        "title": "Userid",
        "type": "string"
      }
    },
    "required": [
      "userId",
      "displayName",
      "role"
    ],
    "title": "AssigneeResponse",
    "type": "object"
  },
  "AssistantCatalogResponse": {
    "additionalProperties": false,
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/AssistantProfileSummary"
        },
        "maxItems": 20,
        "title": "Items",
        "type": "array"
      }
    },
    "required": [
      "items"
    ],
    "title": "AssistantCatalogResponse",
    "type": "object"
  },
  "AssistantProfileSummary": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "modelId": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Modelid"
      },
      "name": {
        "maxLength": 60,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      }
    },
    "required": [
      "id",
      "name",
      "modelId"
    ],
    "title": "AssistantProfileSummary",
    "type": "object"
  },
  "AssistantSelectionRequest": {
    "additionalProperties": false,
    "properties": {
      "expectedRevision": {
        "minimum": 0,
        "title": "Expectedrevision",
        "type": "integer"
      }
    },
    "required": [
      "expectedRevision"
    ],
    "title": "AssistantSelectionRequest",
    "type": "object"
  },
  "AssistantSettingsRequest": {
    "additionalProperties": false,
    "properties": {
      "enabledSkillIds": {
        "items": {
          "type": "string"
        },
        "maxItems": 22,
        "title": "Enabledskillids",
        "type": "array"
      },
      "expectedRevision": {
        "minimum": 0,
        "title": "Expectedrevision",
        "type": "integer"
      },
      "instructions": {
        "maxLength": 2000,
        "title": "Instructions",
        "type": "string"
      },
      "modelId": {
        "anyOf": [
          {
            "pattern": "^[a-z][a-z0-9_-]{0,63}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Modelid"
      },
      "name": {
        "maxLength": 60,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      }
    },
    "required": [
      "expectedRevision",
      "name",
      "instructions",
      "enabledSkillIds"
    ],
    "title": "AssistantSettingsRequest",
    "type": "object"
  },
  "AssistantSettingsResponse": {
    "additionalProperties": false,
    "properties": {
      "enabledSkillIds": {
        "items": {
          "type": "string"
        },
        "maxItems": 22,
        "title": "Enabledskillids",
        "type": "array"
      },
      "id": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Id"
      },
      "instructions": {
        "maxLength": 2000,
        "title": "Instructions",
        "type": "string"
      },
      "modelId": {
        "anyOf": [
          {
            "maxLength": 64,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Modelid"
      },
      "name": {
        "maxLength": 60,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      },
      "revision": {
        "minimum": 0,
        "title": "Revision",
        "type": "integer"
      }
    },
    "required": [
      "name",
      "instructions",
      "enabledSkillIds",
      "revision"
    ],
    "title": "AssistantSettingsResponse",
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
  "DependencyPage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/DependencyResponse"
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
    "title": "DependencyPage",
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
  "FeishuSourceCreateRequest": {
    "additionalProperties": false,
    "properties": {
      "accessPolicy": {
        "const": "project_members",
        "title": "Accesspolicy",
        "type": "string"
      },
      "credentialRef": {
        "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
        "title": "Credentialref",
        "type": "string"
      },
      "documentId": {
        "pattern": "^[A-Za-z0-9]{1,128}$",
        "title": "Documentid",
        "type": "string"
      },
      "name": {
        "maxLength": 200,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      },
      "syncIntervalSeconds": {
        "anyOf": [
          {
            "maximum": 604800,
            "minimum": 300,
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "title": "Syncintervalseconds"
      }
    },
    "required": [
      "name",
      "documentId",
      "credentialRef",
      "accessPolicy"
    ],
    "title": "FeishuSourceCreateRequest",
    "type": "object"
  },
  "FeishuSourcePatchRequest": {
    "oneOf": [
      {
        "anyOf": [
          {
            "additionalProperties": false,
            "properties": {
              "credentialRef": false,
              "name": {
                "maxLength": 200,
                "minLength": 1,
                "type": "string"
              },
              "status": {
                "const": "disabled",
                "type": "string"
              },
              "syncIntervalSeconds": {
                "anyOf": [
                  {
                    "maximum": 604800,
                    "minimum": 300,
                    "type": "integer"
                  },
                  {
                    "type": "null"
                  }
                ],
                "title": "Syncintervalseconds"
              }
            },
            "required": [
              "name"
            ],
            "type": "object"
          },
          {
            "additionalProperties": false,
            "properties": {
              "credentialRef": false,
              "name": {
                "maxLength": 200,
                "minLength": 1,
                "type": "string"
              },
              "status": {
                "const": "disabled",
                "type": "string"
              },
              "syncIntervalSeconds": {
                "anyOf": [
                  {
                    "maximum": 604800,
                    "minimum": 300,
                    "type": "integer"
                  },
                  {
                    "type": "null"
                  }
                ],
                "title": "Syncintervalseconds"
              }
            },
            "required": [
              "status"
            ],
            "type": "object"
          },
          {
            "additionalProperties": false,
            "properties": {
              "credentialRef": false,
              "name": {
                "maxLength": 200,
                "minLength": 1,
                "type": "string"
              },
              "status": {
                "const": "disabled",
                "type": "string"
              },
              "syncIntervalSeconds": {
                "anyOf": [
                  {
                    "maximum": 604800,
                    "minimum": 300,
                    "type": "integer"
                  },
                  {
                    "type": "null"
                  }
                ],
                "title": "Syncintervalseconds"
              }
            },
            "required": [
              "syncIntervalSeconds"
            ],
            "type": "object"
          }
        ]
      },
      {
        "anyOf": [
          {
            "additionalProperties": false,
            "properties": {
              "accessPolicy": {
                "const": "project_members",
                "type": "string"
              },
              "credentialRef": {
                "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
                "type": "string"
              },
              "name": {
                "maxLength": 200,
                "minLength": 1,
                "type": "string"
              },
              "status": {
                "enum": [
                  "configured",
                  "disabled"
                ],
                "type": "string"
              },
              "syncIntervalSeconds": {
                "anyOf": [
                  {
                    "maximum": 604800,
                    "minimum": 300,
                    "type": "integer"
                  },
                  {
                    "type": "null"
                  }
                ],
                "title": "Syncintervalseconds"
              }
            },
            "required": [
              "accessPolicy",
              "name"
            ],
            "type": "object"
          },
          {
            "additionalProperties": false,
            "properties": {
              "accessPolicy": {
                "const": "project_members",
                "type": "string"
              },
              "credentialRef": {
                "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
                "type": "string"
              },
              "name": {
                "maxLength": 200,
                "minLength": 1,
                "type": "string"
              },
              "status": {
                "enum": [
                  "configured",
                  "disabled"
                ],
                "type": "string"
              },
              "syncIntervalSeconds": {
                "anyOf": [
                  {
                    "maximum": 604800,
                    "minimum": 300,
                    "type": "integer"
                  },
                  {
                    "type": "null"
                  }
                ],
                "title": "Syncintervalseconds"
              }
            },
            "required": [
              "accessPolicy",
              "credentialRef"
            ],
            "type": "object"
          },
          {
            "additionalProperties": false,
            "properties": {
              "accessPolicy": {
                "const": "project_members",
                "type": "string"
              },
              "credentialRef": {
                "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
                "type": "string"
              },
              "name": {
                "maxLength": 200,
                "minLength": 1,
                "type": "string"
              },
              "status": {
                "enum": [
                  "configured",
                  "disabled"
                ],
                "type": "string"
              },
              "syncIntervalSeconds": {
                "anyOf": [
                  {
                    "maximum": 604800,
                    "minimum": 300,
                    "type": "integer"
                  },
                  {
                    "type": "null"
                  }
                ],
                "title": "Syncintervalseconds"
              }
            },
            "required": [
              "accessPolicy",
              "status"
            ],
            "type": "object"
          },
          {
            "additionalProperties": false,
            "properties": {
              "accessPolicy": {
                "const": "project_members",
                "type": "string"
              },
              "credentialRef": {
                "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
                "type": "string"
              },
              "name": {
                "maxLength": 200,
                "minLength": 1,
                "type": "string"
              },
              "status": {
                "enum": [
                  "configured",
                  "disabled"
                ],
                "type": "string"
              },
              "syncIntervalSeconds": {
                "anyOf": [
                  {
                    "maximum": 604800,
                    "minimum": 300,
                    "type": "integer"
                  },
                  {
                    "type": "null"
                  }
                ],
                "title": "Syncintervalseconds"
              }
            },
            "required": [
              "accessPolicy",
              "syncIntervalSeconds"
            ],
            "type": "object"
          }
        ]
      }
    ],
    "title": "FeishuSourcePatchRequest"
  },
  "GithubSkillSource": {
    "additionalProperties": false,
    "properties": {
      "path": {
        "anyOf": [
          {
            "maxLength": 500,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Path"
      },
      "ref": {
        "anyOf": [
          {
            "maxLength": 128,
            "minLength": 1,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Ref"
      },
      "type": {
        "const": "github",
        "title": "Type",
        "type": "string"
      },
      "url": {
        "maxLength": 1024,
        "minLength": 1,
        "title": "Url",
        "type": "string"
      }
    },
    "required": [
      "type",
      "url"
    ],
    "title": "GithubSkillSource",
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
  "KnowledgeAnswerCitation": {
    "additionalProperties": false,
    "properties": {
      "chunkId": {
        "format": "uuid",
        "title": "Chunkid",
        "type": "string"
      },
      "excerpt": {
        "title": "Excerpt",
        "type": "string"
      },
      "id": {
        "pattern": "^S[1-6]$",
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
      "mediaType": {
        "title": "Mediatype",
        "type": "string"
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
      },
      "score": {
        "title": "Score",
        "type": "number"
      },
      "title": {
        "title": "Title",
        "type": "string"
      }
    },
    "required": [
      "resourceId",
      "resourceVersionId",
      "chunkId",
      "title",
      "mediaType",
      "excerpt",
      "locator",
      "score",
      "id"
    ],
    "title": "KnowledgeAnswerCitation",
    "type": "object"
  },
  "KnowledgeAnswerModelStatus": {
    "additionalProperties": false,
    "properties": {
      "configured": {
        "title": "Configured",
        "type": "boolean"
      },
      "defaultModelId": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Defaultmodelid"
      },
      "model": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Model"
      },
      "models": {
        "items": {
          "$ref": "#/components/schemas/AnswerModelOption"
        },
        "title": "Models",
        "type": "array"
      },
      "protocol": {
        "anyOf": [
          {
            "enum": [
              "openai-compatible",
              "openai-responses",
              "anthropic",
              "gemini"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Protocol"
      }
    },
    "required": [
      "configured",
      "model",
      "protocol",
      "defaultModelId",
      "models"
    ],
    "title": "KnowledgeAnswerModelStatus",
    "type": "object"
  },
  "KnowledgeAnswerParagraph": {
    "additionalProperties": false,
    "properties": {
      "citationIds": {
        "items": {
          "type": "string"
        },
        "maxItems": 6,
        "minItems": 1,
        "title": "Citationids",
        "type": "array"
      },
      "text": {
        "maxLength": 1000,
        "minLength": 1,
        "title": "Text",
        "type": "string"
      }
    },
    "required": [
      "text",
      "citationIds"
    ],
    "title": "KnowledgeAnswerParagraph",
    "type": "object"
  },
  "KnowledgeAnswerRequest": {
    "additionalProperties": false,
    "properties": {
      "question": {
        "maxLength": 500,
        "minLength": 3,
        "title": "Question",
        "type": "string"
      }
    },
    "required": [
      "question"
    ],
    "title": "KnowledgeAnswerRequest",
    "type": "object"
  },
  "KnowledgeAnswerResponse": {
    "additionalProperties": false,
    "properties": {
      "citations": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeAnswerCitation"
        },
        "maxItems": 6,
        "title": "Citations",
        "type": "array"
      },
      "paragraphs": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeAnswerParagraph"
        },
        "maxItems": 8,
        "title": "Paragraphs",
        "type": "array"
      },
      "retrievalMode": {
        "enum": [
          "hybrid",
          "keyword_fallback"
        ],
        "title": "Retrievalmode",
        "type": "string"
      },
      "status": {
        "enum": [
          "answered",
          "insufficient_evidence"
        ],
        "title": "Status",
        "type": "string"
      }
    },
    "required": [
      "status",
      "retrievalMode",
      "paragraphs",
      "citations"
    ],
    "title": "KnowledgeAnswerResponse",
    "type": "object"
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
  "KnowledgeCitation": {
    "properties": {
      "chunkId": {
        "format": "uuid",
        "title": "Chunkid",
        "type": "string"
      },
      "excerpt": {
        "title": "Excerpt",
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
      "mediaType": {
        "title": "Mediatype",
        "type": "string"
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
      },
      "score": {
        "title": "Score",
        "type": "number"
      },
      "title": {
        "title": "Title",
        "type": "string"
      }
    },
    "required": [
      "resourceId",
      "resourceVersionId",
      "chunkId",
      "title",
      "mediaType",
      "excerpt",
      "locator",
      "score"
    ],
    "title": "KnowledgeCitation",
    "type": "object"
  },
  "KnowledgeContent": {
    "additionalProperties": false,
    "properties": {
      "content": {
        "title": "Content",
        "type": "string"
      },
      "format": {
        "enum": [
          "markdown",
          "text"
        ],
        "title": "Format",
        "type": "string"
      },
      "highlight": {
        "anyOf": [
          {
            "$ref": "#/components/schemas/KnowledgeContentHighlight"
          },
          {
            "type": "null"
          }
        ]
      },
      "lineCount": {
        "maximum": 20000,
        "minimum": 1,
        "title": "Linecount",
        "type": "integer"
      },
      "mediaType": {
        "title": "Mediatype",
        "type": "string"
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
      },
      "title": {
        "title": "Title",
        "type": "string"
      }
    },
    "required": [
      "resourceId",
      "resourceVersionId",
      "title",
      "mediaType",
      "format",
      "content",
      "lineCount",
      "highlight"
    ],
    "title": "KnowledgeContent",
    "type": "object"
  },
  "KnowledgeContentHighlight": {
    "additionalProperties": false,
    "properties": {
      "chunkId": {
        "format": "uuid",
        "title": "Chunkid",
        "type": "string"
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
      "matchType": {
        "enum": [
          "exact",
          "range"
        ],
        "title": "Matchtype",
        "type": "string"
      },
      "text": {
        "title": "Text",
        "type": "string"
      }
    },
    "required": [
      "chunkId",
      "lineStart",
      "lineEnd",
      "text",
      "matchType"
    ],
    "title": "KnowledgeContentHighlight",
    "type": "object"
  },
  "KnowledgeConversationCompleteEvent": {
    "additionalProperties": false,
    "properties": {
      "conversation": {
        "$ref": "#/components/schemas/KnowledgeConversationResponse"
      },
      "conversationId": {
        "format": "uuid",
        "title": "Conversationid",
        "type": "string"
      },
      "turnId": {
        "format": "uuid",
        "title": "Turnid",
        "type": "string"
      },
      "type": {
        "const": "complete",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "type",
      "conversationId",
      "turnId",
      "conversation"
    ],
    "title": "KnowledgeConversationCompleteEvent",
    "type": "object"
  },
  "KnowledgeConversationCreateRequest": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      }
    },
    "required": [
      "id"
    ],
    "title": "KnowledgeConversationCreateRequest",
    "type": "object"
  },
  "KnowledgeConversationErrorEvent": {
    "additionalProperties": false,
    "properties": {
      "code": {
        "title": "Code",
        "type": "string"
      },
      "conversationId": {
        "format": "uuid",
        "title": "Conversationid",
        "type": "string"
      },
      "message": {
        "title": "Message",
        "type": "string"
      },
      "retryAfter": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Retryafter"
      },
      "status": {
        "maximum": 599,
        "minimum": 400,
        "title": "Status",
        "type": "integer"
      },
      "traceId": {
        "title": "Traceid",
        "type": "string"
      },
      "turnId": {
        "format": "uuid",
        "title": "Turnid",
        "type": "string"
      },
      "type": {
        "const": "error",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "type",
      "conversationId",
      "turnId",
      "status",
      "code",
      "message",
      "traceId",
      "retryAfter"
    ],
    "title": "KnowledgeConversationErrorEvent",
    "type": "object"
  },
  "KnowledgeConversationPage": {
    "additionalProperties": false,
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeConversationSummary"
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
    "title": "KnowledgeConversationPage",
    "type": "object"
  },
  "KnowledgeConversationParagraphEvent": {
    "additionalProperties": false,
    "properties": {
      "conversationId": {
        "format": "uuid",
        "title": "Conversationid",
        "type": "string"
      },
      "index": {
        "maximum": 7,
        "minimum": 0,
        "title": "Index",
        "type": "integer"
      },
      "paragraph": {
        "$ref": "#/components/schemas/KnowledgeAnswerParagraph"
      },
      "turnId": {
        "format": "uuid",
        "title": "Turnid",
        "type": "string"
      },
      "type": {
        "const": "paragraph",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "type",
      "conversationId",
      "turnId",
      "index",
      "paragraph"
    ],
    "title": "KnowledgeConversationParagraphEvent",
    "type": "object"
  },
  "KnowledgeConversationResponse": {
    "additionalProperties": false,
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
      "revision": {
        "maximum": 51,
        "minimum": 1,
        "title": "Revision",
        "type": "integer"
      },
      "title": {
        "maxLength": 60,
        "minLength": 1,
        "title": "Title",
        "type": "string"
      },
      "turns": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeConversationTurnResponse"
        },
        "maxItems": 50,
        "title": "Turns",
        "type": "array"
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
      "revision",
      "createdAt",
      "updatedAt",
      "turns"
    ],
    "title": "KnowledgeConversationResponse",
    "type": "object"
  },
  "KnowledgeConversationStreamEvent": {
    "discriminator": {
      "mapping": {
        "complete": "#/components/schemas/KnowledgeConversationCompleteEvent",
        "error": "#/components/schemas/KnowledgeConversationErrorEvent",
        "paragraph": "#/components/schemas/KnowledgeConversationParagraphEvent"
      },
      "propertyName": "type"
    },
    "oneOf": [
      {
        "$ref": "#/components/schemas/KnowledgeConversationParagraphEvent"
      },
      {
        "$ref": "#/components/schemas/KnowledgeConversationCompleteEvent"
      },
      {
        "$ref": "#/components/schemas/KnowledgeConversationErrorEvent"
      }
    ],
    "title": "KnowledgeConversationStreamEvent"
  },
  "KnowledgeConversationSummary": {
    "additionalProperties": false,
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
      "revision": {
        "maximum": 51,
        "minimum": 1,
        "title": "Revision",
        "type": "integer"
      },
      "title": {
        "maxLength": 60,
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
      "title",
      "revision",
      "createdAt",
      "updatedAt"
    ],
    "title": "KnowledgeConversationSummary",
    "type": "object"
  },
  "KnowledgeConversationTurnRequest": {
    "additionalProperties": false,
    "properties": {
      "assistantRevision": {
        "default": 0,
        "minimum": 0,
        "title": "Assistantrevision",
        "type": "integer"
      },
      "expectedRevision": {
        "exclusiveMinimum": 0,
        "title": "Expectedrevision",
        "type": "integer"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "question": {
        "maxLength": 500,
        "minLength": 3,
        "title": "Question",
        "type": "string"
      },
      "skillId": {
        "anyOf": [
          {
            "maxLength": 64,
            "minLength": 1,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Skillid"
      }
    },
    "required": [
      "question",
      "id",
      "expectedRevision"
    ],
    "title": "KnowledgeConversationTurnRequest",
    "type": "object"
  },
  "KnowledgeConversationTurnResponse": {
    "additionalProperties": false,
    "properties": {
      "answer": {
        "anyOf": [
          {
            "$ref": "#/components/schemas/KnowledgeAnswerResponse"
          },
          {
            "type": "null"
          }
        ]
      },
      "answerUnavailable": {
        "title": "Answerunavailable",
        "type": "boolean"
      },
      "assistantId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Assistantid"
      },
      "assistantName": {
        "default": "岑宁",
        "title": "Assistantname",
        "type": "string"
      },
      "assistantRevision": {
        "default": 0,
        "minimum": 0,
        "title": "Assistantrevision",
        "type": "integer"
      },
      "contextTruncated": {
        "title": "Contexttruncated",
        "type": "boolean"
      },
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
      "model": {
        "anyOf": [
          {
            "$ref": "#/components/schemas/AnswerModelOption"
          },
          {
            "type": "null"
          }
        ]
      },
      "question": {
        "maxLength": 500,
        "minLength": 3,
        "title": "Question",
        "type": "string"
      },
      "sequence": {
        "maximum": 50,
        "minimum": 1,
        "title": "Sequence",
        "type": "integer"
      },
      "skillId": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Skillid"
      }
    },
    "required": [
      "id",
      "sequence",
      "question",
      "answer",
      "answerUnavailable",
      "contextTruncated",
      "createdAt"
    ],
    "title": "KnowledgeConversationTurnResponse",
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
  "KnowledgeSearchRequest": {
    "additionalProperties": false,
    "properties": {
      "limit": {
        "default": 10,
        "maximum": 20,
        "minimum": 1,
        "title": "Limit",
        "type": "integer"
      },
      "query": {
        "maxLength": 500,
        "minLength": 3,
        "title": "Query",
        "type": "string"
      }
    },
    "required": [
      "query"
    ],
    "title": "KnowledgeSearchRequest",
    "type": "object"
  },
  "KnowledgeSearchResponse": {
    "properties": {
      "results": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeCitation"
        },
        "title": "Results",
        "type": "array"
      },
      "retrievalMode": {
        "enum": [
          "hybrid",
          "keyword_fallback"
        ],
        "title": "Retrievalmode",
        "type": "string"
      }
    },
    "required": [
      "retrievalMode",
      "results"
    ],
    "title": "KnowledgeSearchResponse",
    "type": "object"
  },
  "KnowledgeSkillCatalogResponse": {
    "additionalProperties": false,
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeSkillItem"
        },
        "title": "Items",
        "type": "array"
      }
    },
    "required": [
      "items"
    ],
    "title": "KnowledgeSkillCatalogResponse",
    "type": "object"
  },
  "KnowledgeSkillImportResponse": {
    "additionalProperties": false,
    "properties": {
      "body": {
        "title": "Body",
        "type": "string"
      },
      "capabilities": {
        "items": {
          "const": "knowledge.read",
          "type": "string"
        },
        "title": "Capabilities",
        "type": "array"
      },
      "defaultQuestion": {
        "title": "Defaultquestion",
        "type": "string"
      },
      "description": {
        "title": "Description",
        "type": "string"
      },
      "digest": {
        "title": "Digest",
        "type": "string"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "name": {
        "title": "Name",
        "type": "string"
      },
      "resources": {
        "items": {
          "$ref": "#/components/schemas/SkillResource"
        },
        "title": "Resources",
        "type": "array"
      },
      "runnable": {
        "title": "Runnable",
        "type": "boolean"
      },
      "sourceMetadata": {
        "additionalProperties": {
          "type": "string"
        },
        "title": "Sourcemetadata",
        "type": "object"
      },
      "sourceType": {
        "enum": [
          "markdown",
          "zip",
          "github"
        ],
        "title": "Sourcetype",
        "type": "string"
      },
      "version": {
        "const": "v1",
        "default": "v1",
        "title": "Version",
        "type": "string"
      },
      "warnings": {
        "items": {
          "type": "string"
        },
        "title": "Warnings",
        "type": "array"
      }
    },
    "required": [
      "name",
      "description",
      "defaultQuestion",
      "capabilities",
      "sourceType",
      "sourceMetadata",
      "runnable",
      "warnings",
      "body",
      "resources",
      "digest",
      "id"
    ],
    "title": "KnowledgeSkillImportResponse",
    "type": "object"
  },
  "KnowledgeSkillItem": {
    "additionalProperties": false,
    "properties": {
      "capabilities": {
        "items": {
          "const": "knowledge.read",
          "type": "string"
        },
        "title": "Capabilities",
        "type": "array"
      },
      "defaultQuestion": {
        "title": "Defaultquestion",
        "type": "string"
      },
      "description": {
        "title": "Description",
        "type": "string"
      },
      "id": {
        "title": "Id",
        "type": "string"
      },
      "name": {
        "title": "Name",
        "type": "string"
      },
      "runnable": {
        "title": "Runnable",
        "type": "boolean"
      },
      "sourceType": {
        "enum": [
          "builtin",
          "markdown",
          "zip",
          "github"
        ],
        "title": "Sourcetype",
        "type": "string"
      },
      "version": {
        "const": "v1",
        "default": "v1",
        "title": "Version",
        "type": "string"
      },
      "warnings": {
        "items": {
          "type": "string"
        },
        "title": "Warnings",
        "type": "array"
      }
    },
    "required": [
      "id",
      "name",
      "description",
      "defaultQuestion",
      "capabilities",
      "sourceType",
      "runnable",
      "warnings"
    ],
    "title": "KnowledgeSkillItem",
    "type": "object"
  },
  "KnowledgeSkillPreview": {
    "additionalProperties": false,
    "properties": {
      "body": {
        "title": "Body",
        "type": "string"
      },
      "capabilities": {
        "items": {
          "const": "knowledge.read",
          "type": "string"
        },
        "title": "Capabilities",
        "type": "array"
      },
      "defaultQuestion": {
        "title": "Defaultquestion",
        "type": "string"
      },
      "description": {
        "title": "Description",
        "type": "string"
      },
      "digest": {
        "title": "Digest",
        "type": "string"
      },
      "name": {
        "title": "Name",
        "type": "string"
      },
      "resources": {
        "items": {
          "$ref": "#/components/schemas/SkillResource"
        },
        "title": "Resources",
        "type": "array"
      },
      "runnable": {
        "title": "Runnable",
        "type": "boolean"
      },
      "sourceMetadata": {
        "additionalProperties": {
          "type": "string"
        },
        "title": "Sourcemetadata",
        "type": "object"
      },
      "sourceType": {
        "enum": [
          "markdown",
          "zip",
          "github"
        ],
        "title": "Sourcetype",
        "type": "string"
      },
      "version": {
        "const": "v1",
        "default": "v1",
        "title": "Version",
        "type": "string"
      },
      "warnings": {
        "items": {
          "type": "string"
        },
        "title": "Warnings",
        "type": "array"
      }
    },
    "required": [
      "name",
      "description",
      "defaultQuestion",
      "capabilities",
      "sourceType",
      "sourceMetadata",
      "runnable",
      "warnings",
      "body",
      "resources",
      "digest"
    ],
    "title": "KnowledgeSkillPreview",
    "type": "object"
  },
  "KnowledgeSourcePage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeSourceResponse"
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
    "title": "KnowledgeSourcePage",
    "type": "object"
  },
  "KnowledgeSourceResponse": {
    "properties": {
      "accessPolicy": {
        "const": "project_members",
        "title": "Accesspolicy",
        "type": "string"
      },
      "accessState": {
        "enum": [
          "available",
          "unverified",
          "access_denied",
          "not_found"
        ],
        "title": "Accessstate",
        "type": "string"
      },
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
      "credentialRef": {
        "title": "Credentialref",
        "type": "string"
      },
      "disabledAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Disabledat"
      },
      "documentId": {
        "title": "Documentid",
        "type": "string"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "lastCheckedAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Lastcheckedat"
      },
      "lastErrorCode": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Lasterrorcode"
      },
      "lastSuccessAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Lastsuccessat"
      },
      "name": {
        "title": "Name",
        "type": "string"
      },
      "nextSyncAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Nextsyncat"
      },
      "projectId": {
        "format": "uuid",
        "title": "Projectid",
        "type": "string"
      },
      "provider": {
        "const": "feishu",
        "title": "Provider",
        "type": "string"
      },
      "status": {
        "enum": [
          "configured",
          "disabled"
        ],
        "title": "Status",
        "type": "string"
      },
      "syncIntervalSeconds": {
        "anyOf": [
          {
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "title": "Syncintervalseconds"
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
      "provider",
      "name",
      "documentId",
      "credentialRef",
      "accessPolicy",
      "status",
      "createdAt",
      "updatedAt",
      "disabledAt",
      "syncIntervalSeconds",
      "nextSyncAt",
      "lastCheckedAt",
      "lastSuccessAt",
      "lastErrorCode",
      "accessState"
    ],
    "title": "KnowledgeSourceResponse",
    "type": "object"
  },
  "KnowledgeSourceSyncCreateRequest": {
    "additionalProperties": false,
    "properties": {},
    "title": "KnowledgeSourceSyncCreateRequest",
    "type": "object"
  },
  "KnowledgeSourceSyncPage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeSourceSyncResponse"
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
    "title": "KnowledgeSourceSyncPage",
    "type": "object"
  },
  "KnowledgeSourceSyncResponse": {
    "properties": {
      "attempt": {
        "title": "Attempt",
        "type": "integer"
      },
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
      "failureCode": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Failurecode"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "nextAttemptAt": {
        "anyOf": [
          {
            "format": "date-time",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Nextattemptat"
      },
      "projectId": {
        "format": "uuid",
        "title": "Projectid",
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
      "resourceStatus": {
        "anyOf": [
          {
            "enum": [
              "queued",
              "processing",
              "ready",
              "failed"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Resourcestatus"
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
      "sourceId": {
        "format": "uuid",
        "title": "Sourceid",
        "type": "string"
      },
      "status": {
        "enum": [
          "queued",
          "running",
          "completed",
          "failed"
        ],
        "title": "Status",
        "type": "string"
      },
      "trigger": {
        "enum": [
          "manual",
          "scheduled"
        ],
        "title": "Trigger",
        "type": "string"
      }
    },
    "required": [
      "id",
      "projectId",
      "sourceId",
      "status",
      "attempt",
      "createdAt",
      "completedAt",
      "errorCode",
      "resourceId",
      "resourceVersionId",
      "trigger",
      "failureCode",
      "nextAttemptAt",
      "resourceStatus"
    ],
    "title": "KnowledgeSourceSyncResponse",
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
  "LinkedIdentitiesResponse": {
    "properties": {
      "identities": {
        "items": {
          "$ref": "#/components/schemas/LinkedIdentityResponse"
        },
        "title": "Identities",
        "type": "array"
      },
      "passwordAvailable": {
        "title": "Passwordavailable",
        "type": "boolean"
      }
    },
    "required": [
      "identities",
      "passwordAvailable"
    ],
    "title": "LinkedIdentitiesResponse",
    "type": "object"
  },
  "LinkedIdentityResponse": {
    "properties": {
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
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
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "provider": {
        "enum": [
          "github",
          "feishu"
        ],
        "title": "Provider",
        "type": "string"
      }
    },
    "required": [
      "id",
      "provider",
      "displayName",
      "createdAt"
    ],
    "title": "LinkedIdentityResponse",
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
  "MarkdownSkillSource": {
    "additionalProperties": false,
    "properties": {
      "content": {
        "maxLength": 65536,
        "minLength": 1,
        "title": "Content",
        "type": "string"
      },
      "fileName": {
        "maxLength": 120,
        "minLength": 1,
        "title": "Filename",
        "type": "string"
      },
      "type": {
        "const": "markdown",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "type",
      "fileName",
      "content"
    ],
    "title": "MarkdownSkillSource",
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
        "anyOf": [
          {
            "format": "email",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Email"
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
  "MilestoneCreateRequest": {
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
      "expectedProjectRevision": {
        "minimum": 1,
        "title": "Expectedprojectrevision",
        "type": "integer"
      },
      "name": {
        "maxLength": 160,
        "minLength": 1,
        "title": "Name",
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
      }
    },
    "required": [
      "expectedProjectRevision",
      "name"
    ],
    "title": "MilestoneCreateRequest",
    "type": "object"
  },
  "MilestonePage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/MilestoneResponse"
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
    "title": "MilestonePage",
    "type": "object"
  },
  "MilestoneResponse": {
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
      "archived": {
        "title": "Archived",
        "type": "boolean"
      },
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
      "name": {
        "maxLength": 160,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      },
      "projectId": {
        "format": "uuid",
        "title": "Projectid",
        "type": "string"
      },
      "revision": {
        "minimum": 1,
        "title": "Revision",
        "type": "integer"
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
      "updatedAt": {
        "format": "date-time",
        "title": "Updatedat",
        "type": "string"
      }
    },
    "required": [
      "id",
      "projectId",
      "revision",
      "archived",
      "name",
      "description",
      "acceptanceCriteria",
      "dueAt",
      "stageId",
      "createdAt",
      "updatedAt"
    ],
    "title": "MilestoneResponse",
    "type": "object"
  },
  "MilestoneUpdateRequest": {
    "anyOf": [
      {
        "additionalProperties": false,
        "properties": {
          "acceptanceCriteria": false,
          "archived": {
            "title": "Archived",
            "type": "boolean"
          },
          "description": false,
          "dueAt": false,
          "expectedProjectRevision": {
            "minimum": 1,
            "title": "Expectedprojectrevision",
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "name": false,
          "stageId": false
        },
        "required": [
          "expectedProjectRevision",
          "expectedRevision",
          "archived"
        ],
        "type": "object"
      },
      {
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
          "archived": false,
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
          "expectedProjectRevision": {
            "minimum": 1,
            "title": "Expectedprojectrevision",
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "name": {
            "maxLength": 160,
            "minLength": 1,
            "title": "Name",
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
          }
        },
        "required": [
          "expectedProjectRevision",
          "expectedRevision",
          "name"
        ],
        "type": "object"
      },
      {
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
          "archived": false,
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
          "expectedProjectRevision": {
            "minimum": 1,
            "title": "Expectedprojectrevision",
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "name": {
            "maxLength": 160,
            "minLength": 1,
            "title": "Name",
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
          }
        },
        "required": [
          "expectedProjectRevision",
          "expectedRevision",
          "description"
        ],
        "type": "object"
      },
      {
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
          "archived": false,
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
          "expectedProjectRevision": {
            "minimum": 1,
            "title": "Expectedprojectrevision",
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "name": {
            "maxLength": 160,
            "minLength": 1,
            "title": "Name",
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
          }
        },
        "required": [
          "expectedProjectRevision",
          "expectedRevision",
          "acceptanceCriteria"
        ],
        "type": "object"
      },
      {
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
          "archived": false,
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
          "expectedProjectRevision": {
            "minimum": 1,
            "title": "Expectedprojectrevision",
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "name": {
            "maxLength": 160,
            "minLength": 1,
            "title": "Name",
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
          }
        },
        "required": [
          "expectedProjectRevision",
          "expectedRevision",
          "dueAt"
        ],
        "type": "object"
      },
      {
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
          "archived": false,
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
          "expectedProjectRevision": {
            "minimum": 1,
            "title": "Expectedprojectrevision",
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "name": {
            "maxLength": 160,
            "minLength": 1,
            "title": "Name",
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
          }
        },
        "required": [
          "expectedProjectRevision",
          "expectedRevision",
          "stageId"
        ],
        "type": "object"
      }
    ],
    "title": "MilestoneUpdateRequest"
  },
  "OAuthProviderResponse": {
    "properties": {
      "enabled": {
        "title": "Enabled",
        "type": "boolean"
      },
      "provider": {
        "enum": [
          "github",
          "feishu"
        ],
        "title": "Provider",
        "type": "string"
      }
    },
    "required": [
      "provider",
      "enabled"
    ],
    "title": "OAuthProviderResponse",
    "type": "object"
  },
  "OAuthStartRequest": {
    "additionalProperties": false,
    "properties": {
      "intent": {
        "enum": [
          "login",
          "link"
        ],
        "title": "Intent",
        "type": "string"
      },
      "returnTo": {
        "default": "/projects",
        "enum": [
          "/projects",
          "/account/identities"
        ],
        "title": "Returnto",
        "type": "string"
      }
    },
    "required": [
      "intent"
    ],
    "title": "OAuthStartRequest",
    "type": "object"
  },
  "OAuthStartResponse": {
    "properties": {
      "authorizationUrl": {
        "title": "Authorizationurl",
        "type": "string"
      }
    },
    "required": [
      "authorizationUrl"
    ],
    "title": "OAuthStartResponse",
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
  "ProjectAnalysisResponse": {
    "additionalProperties": false,
    "properties": {
      "assistantName": {
        "title": "Assistantname",
        "type": "string"
      },
      "citations": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeAnswerCitation"
        },
        "maxItems": 5,
        "title": "Citations",
        "type": "array"
      },
      "generatedAt": {
        "format": "date-time",
        "title": "Generatedat",
        "type": "string"
      },
      "model": {
        "$ref": "#/components/schemas/AnswerModelOption"
      },
      "paragraphs": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeAnswerParagraph"
        },
        "maxItems": 8,
        "title": "Paragraphs",
        "type": "array"
      },
      "projectId": {
        "format": "uuid",
        "title": "Projectid",
        "type": "string"
      },
      "retrievalMode": {
        "enum": [
          "hybrid",
          "keyword_fallback"
        ],
        "title": "Retrievalmode",
        "type": "string"
      },
      "snapshot": {
        "$ref": "#/components/schemas/ProjectAnalysisSnapshot"
      },
      "status": {
        "enum": [
          "answered",
          "insufficient_evidence"
        ],
        "title": "Status",
        "type": "string"
      }
    },
    "required": [
      "projectId",
      "generatedAt",
      "assistantName",
      "model",
      "snapshot",
      "status",
      "retrievalMode",
      "paragraphs",
      "citations"
    ],
    "title": "ProjectAnalysisResponse",
    "type": "object"
  },
  "ProjectAnalysisSnapshot": {
    "additionalProperties": false,
    "properties": {
      "dependencies": {
        "items": {
          "$ref": "#/components/schemas/DependencyResponse"
        },
        "maxItems": 300,
        "title": "Dependencies",
        "type": "array"
      },
      "milestones": {
        "items": {
          "$ref": "#/components/schemas/MilestoneResponse"
        },
        "maxItems": 50,
        "title": "Milestones",
        "type": "array"
      },
      "project": {
        "$ref": "#/components/schemas/ProjectResponse"
      },
      "stages": {
        "items": {
          "$ref": "#/components/schemas/StageResponse"
        },
        "maxItems": 50,
        "title": "Stages",
        "type": "array"
      },
      "tasks": {
        "items": {
          "$ref": "#/components/schemas/TaskResponse"
        },
        "maxItems": 100,
        "title": "Tasks",
        "type": "array"
      }
    },
    "required": [
      "project",
      "stages",
      "milestones",
      "tasks",
      "dependencies"
    ],
    "title": "ProjectAnalysisSnapshot",
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
  "ProjectPermission": {
    "enum": [
      "read",
      "write",
      "manage"
    ],
    "title": "ProjectPermission",
    "type": "string"
  },
  "ProjectPlanDraft": {
    "additionalProperties": false,
    "properties": {
      "assumptions": {
        "items": {
          "maxLength": 400,
          "minLength": 1,
          "type": "string"
        },
        "maxItems": 6,
        "title": "Assumptions",
        "type": "array"
      },
      "citationIds": {
        "items": {
          "pattern": "^S[1-6]$",
          "type": "string"
        },
        "maxItems": 6,
        "title": "Citationids",
        "type": "array"
      },
      "milestones": {
        "items": {
          "$ref": "#/components/schemas/ProposedMilestone"
        },
        "maxItems": 8,
        "title": "Milestones",
        "type": "array"
      },
      "stages": {
        "items": {
          "$ref": "#/components/schemas/ProposedStage"
        },
        "maxItems": 5,
        "title": "Stages",
        "type": "array"
      },
      "status": {
        "enum": [
          "planned",
          "insufficient_evidence"
        ],
        "title": "Status",
        "type": "string"
      },
      "summary": {
        "maxLength": 1000,
        "minLength": 1,
        "title": "Summary",
        "type": "string"
      },
      "tasks": {
        "items": {
          "$ref": "#/components/schemas/ProposedTask"
        },
        "maxItems": 20,
        "title": "Tasks",
        "type": "array"
      }
    },
    "required": [
      "status",
      "summary",
      "assumptions",
      "citationIds",
      "stages",
      "milestones",
      "tasks"
    ],
    "title": "ProjectPlanDraft",
    "type": "object"
  },
  "ProjectPlanPreviewResponse": {
    "additionalProperties": false,
    "properties": {
      "assistantName": {
        "title": "Assistantname",
        "type": "string"
      },
      "citations": {
        "items": {
          "$ref": "#/components/schemas/KnowledgeAnswerCitation"
        },
        "maxItems": 5,
        "title": "Citations",
        "type": "array"
      },
      "generatedAt": {
        "format": "date-time",
        "title": "Generatedat",
        "type": "string"
      },
      "model": {
        "$ref": "#/components/schemas/AnswerModelOption"
      },
      "plan": {
        "$ref": "#/components/schemas/ProjectPlanDraft"
      },
      "projectId": {
        "format": "uuid",
        "title": "Projectid",
        "type": "string"
      },
      "retrievalMode": {
        "enum": [
          "hybrid",
          "keyword_fallback"
        ],
        "title": "Retrievalmode",
        "type": "string"
      },
      "snapshot": {
        "$ref": "#/components/schemas/ProjectAnalysisSnapshot"
      }
    },
    "required": [
      "projectId",
      "generatedAt",
      "assistantName",
      "model",
      "snapshot",
      "retrievalMode",
      "citations",
      "plan"
    ],
    "title": "ProjectPlanPreviewResponse",
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
      "revision": {
        "anyOf": [
          {
            "minimum": 1,
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "title": "Revision"
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
  "ProposedMilestone": {
    "additionalProperties": false,
    "properties": {
      "acceptanceCriteria": {
        "maxLength": 600,
        "minLength": 1,
        "title": "Acceptancecriteria",
        "type": "string"
      },
      "citationIds": {
        "items": {
          "pattern": "^S[1-6]$",
          "type": "string"
        },
        "maxItems": 6,
        "minItems": 1,
        "title": "Citationids",
        "type": "array"
      },
      "id": {
        "pattern": "^M[1-8]$",
        "title": "Id",
        "type": "string"
      },
      "name": {
        "maxLength": 160,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      },
      "stageId": {
        "pattern": "^P[1-5]$",
        "title": "Stageid",
        "type": "string"
      }
    },
    "required": [
      "citationIds",
      "id",
      "stageId",
      "name",
      "acceptanceCriteria"
    ],
    "title": "ProposedMilestone",
    "type": "object"
  },
  "ProposedStage": {
    "additionalProperties": false,
    "properties": {
      "citationIds": {
        "items": {
          "pattern": "^S[1-6]$",
          "type": "string"
        },
        "maxItems": 6,
        "minItems": 1,
        "title": "Citationids",
        "type": "array"
      },
      "goal": {
        "maxLength": 600,
        "minLength": 1,
        "title": "Goal",
        "type": "string"
      },
      "id": {
        "pattern": "^P[1-5]$",
        "title": "Id",
        "type": "string"
      },
      "name": {
        "maxLength": 120,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      }
    },
    "required": [
      "citationIds",
      "id",
      "name",
      "goal"
    ],
    "title": "ProposedStage",
    "type": "object"
  },
  "ProposedTask": {
    "additionalProperties": false,
    "properties": {
      "acceptanceCriteria": {
        "maxLength": 600,
        "minLength": 1,
        "title": "Acceptancecriteria",
        "type": "string"
      },
      "citationIds": {
        "items": {
          "pattern": "^S[1-6]$",
          "type": "string"
        },
        "maxItems": 6,
        "minItems": 1,
        "title": "Citationids",
        "type": "array"
      },
      "dependsOn": {
        "items": {
          "pattern": "^T([1-9]|1[0-9]|20)$",
          "type": "string"
        },
        "maxItems": 19,
        "title": "Dependson",
        "type": "array"
      },
      "description": {
        "maxLength": 600,
        "minLength": 1,
        "title": "Description",
        "type": "string"
      },
      "id": {
        "pattern": "^T([1-9]|1[0-9]|20)$",
        "title": "Id",
        "type": "string"
      },
      "milestoneId": {
        "anyOf": [
          {
            "pattern": "^M[1-8]$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Milestoneid"
      },
      "priority": {
        "enum": [
          "low",
          "medium",
          "high",
          "critical"
        ],
        "title": "Priority",
        "type": "string"
      },
      "stageId": {
        "pattern": "^P[1-5]$",
        "title": "Stageid",
        "type": "string"
      },
      "title": {
        "maxLength": 160,
        "minLength": 1,
        "title": "Title",
        "type": "string"
      }
    },
    "required": [
      "citationIds",
      "id",
      "stageId",
      "milestoneId",
      "title",
      "description",
      "acceptanceCriteria",
      "priority",
      "dependsOn"
    ],
    "title": "ProposedTask",
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
  "RegistrationAvailability": {
    "properties": {
      "enabled": {
        "title": "Enabled",
        "type": "boolean"
      }
    },
    "required": [
      "enabled"
    ],
    "title": "RegistrationAvailability",
    "type": "object"
  },
  "RegistrationCreated": {
    "properties": {
      "message": {
        "default": "账号已创建，请使用邮箱和密码登录。邮箱仅作为登录标识。",
        "title": "Message",
        "type": "string"
      }
    },
    "required": [
      "message"
    ],
    "title": "RegistrationCreated",
    "type": "object"
  },
  "RegistrationRequest": {
    "properties": {
      "displayName": {
        "anyOf": [
          {
            "maxLength": 120,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Displayname"
      },
      "email": {
        "format": "email",
        "maxLength": 320,
        "title": "Email",
        "type": "string"
      },
      "password": {
        "maxLength": 128,
        "minLength": 12,
        "title": "Password",
        "type": "string"
      }
    },
    "required": [
      "email",
      "password"
    ],
    "title": "RegistrationRequest",
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
  "SkillImportRequest": {
    "additionalProperties": false,
    "properties": {
      "expectedDigest": {
        "pattern": "^[0-9a-f]{64}$",
        "title": "Expecteddigest",
        "type": "string"
      },
      "id": {
        "format": "uuid",
        "title": "Id",
        "type": "string"
      },
      "source": {
        "discriminator": {
          "mapping": {
            "github": "#/components/schemas/GithubSkillSource",
            "markdown": "#/components/schemas/MarkdownSkillSource",
            "zip": "#/components/schemas/ZipSkillSource"
          },
          "propertyName": "type"
        },
        "oneOf": [
          {
            "$ref": "#/components/schemas/MarkdownSkillSource"
          },
          {
            "$ref": "#/components/schemas/ZipSkillSource"
          },
          {
            "$ref": "#/components/schemas/GithubSkillSource"
          }
        ],
        "title": "Source"
      }
    },
    "required": [
      "source",
      "id",
      "expectedDigest"
    ],
    "title": "SkillImportRequest",
    "type": "object"
  },
  "SkillPreviewRequest": {
    "additionalProperties": false,
    "properties": {
      "source": {
        "discriminator": {
          "mapping": {
            "github": "#/components/schemas/GithubSkillSource",
            "markdown": "#/components/schemas/MarkdownSkillSource",
            "zip": "#/components/schemas/ZipSkillSource"
          },
          "propertyName": "type"
        },
        "oneOf": [
          {
            "$ref": "#/components/schemas/MarkdownSkillSource"
          },
          {
            "$ref": "#/components/schemas/ZipSkillSource"
          },
          {
            "$ref": "#/components/schemas/GithubSkillSource"
          }
        ],
        "title": "Source"
      }
    },
    "required": [
      "source"
    ],
    "title": "SkillPreviewRequest",
    "type": "object"
  },
  "SkillResource": {
    "additionalProperties": false,
    "properties": {
      "content": {
        "title": "Content",
        "type": "string"
      },
      "path": {
        "title": "Path",
        "type": "string"
      }
    },
    "required": [
      "path",
      "content"
    ],
    "title": "SkillResource",
    "type": "object"
  },
  "StageCreateRequest": {
    "additionalProperties": false,
    "properties": {
      "expectedProjectRevision": {
        "minimum": 1,
        "title": "Expectedprojectrevision",
        "type": "integer"
      },
      "name": {
        "maxLength": 120,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      },
      "position": {
        "maximum": 2147483647,
        "minimum": 0,
        "title": "Position",
        "type": "integer"
      }
    },
    "required": [
      "expectedProjectRevision",
      "name",
      "position"
    ],
    "title": "StageCreateRequest",
    "type": "object"
  },
  "StagePage": {
    "properties": {
      "items": {
        "items": {
          "$ref": "#/components/schemas/StageResponse"
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
    "title": "StagePage",
    "type": "object"
  },
  "StageResponse": {
    "properties": {
      "archived": {
        "title": "Archived",
        "type": "boolean"
      },
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
      "name": {
        "maxLength": 120,
        "minLength": 1,
        "title": "Name",
        "type": "string"
      },
      "position": {
        "title": "Position",
        "type": "integer"
      },
      "projectId": {
        "format": "uuid",
        "title": "Projectid",
        "type": "string"
      },
      "revision": {
        "minimum": 1,
        "title": "Revision",
        "type": "integer"
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
      "revision",
      "archived",
      "name",
      "position",
      "createdAt",
      "updatedAt"
    ],
    "title": "StageResponse",
    "type": "object"
  },
  "StageUpdateRequest": {
    "anyOf": [
      {
        "additionalProperties": false,
        "properties": {
          "archived": {
            "title": "Archived",
            "type": "boolean"
          },
          "expectedProjectRevision": {
            "minimum": 1,
            "title": "Expectedprojectrevision",
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "name": false,
          "position": false
        },
        "required": [
          "expectedProjectRevision",
          "expectedRevision",
          "archived"
        ],
        "type": "object"
      },
      {
        "additionalProperties": false,
        "properties": {
          "archived": false,
          "expectedProjectRevision": {
            "minimum": 1,
            "title": "Expectedprojectrevision",
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "name": {
            "maxLength": 120,
            "minLength": 1,
            "title": "Name",
            "type": "string"
          },
          "position": {
            "maximum": 2147483647,
            "minimum": 0,
            "title": "Position",
            "type": "integer"
          }
        },
        "required": [
          "expectedProjectRevision",
          "expectedRevision",
          "name"
        ],
        "type": "object"
      },
      {
        "additionalProperties": false,
        "properties": {
          "archived": false,
          "expectedProjectRevision": {
            "minimum": 1,
            "title": "Expectedprojectrevision",
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "name": {
            "maxLength": 120,
            "minLength": 1,
            "title": "Name",
            "type": "string"
          },
          "position": {
            "maximum": 2147483647,
            "minimum": 0,
            "title": "Position",
            "type": "integer"
          }
        },
        "required": [
          "expectedProjectRevision",
          "expectedRevision",
          "position"
        ],
        "type": "object"
      }
    ],
    "title": "StageUpdateRequest"
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
      "assigneeUserId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Assigneeuserid"
      },
      "description": {
        "anyOf": [
          {
            "maxLength": 10000,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Description"
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
      "expectedProjectRevision": {
        "anyOf": [
          {
            "minimum": 1,
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "title": "Expectedprojectrevision"
      },
      "milestoneId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Milestoneid"
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
      "expectedRevision": {
        "anyOf": [
          {
            "minimum": 1,
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "title": "Expectedrevision"
      },
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
      "assigneeUserId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Assigneeuserid"
      },
      "createdAt": {
        "format": "date-time",
        "title": "Createdat",
        "type": "string"
      },
      "description": {
        "anyOf": [
          {
            "maxLength": 10000,
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Description"
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
      "milestoneId": {
        "anyOf": [
          {
            "format": "uuid",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Milestoneid"
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
      "revision": {
        "minimum": 1,
        "title": "Revision",
        "type": "integer"
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
      "revision",
      "description",
      "assigneeUserId",
      "title",
      "stageId",
      "milestoneId",
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
      "expectedRevision": {
        "anyOf": [
          {
            "minimum": 1,
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "title": "Expectedrevision"
      },
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
  "TaskUpdateRequest": {
    "anyOf": [
      {
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
          "assigneeUserId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Assigneeuserid"
          },
          "description": {
            "anyOf": [
              {
                "maxLength": 10000,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Description"
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
          "expectedProjectRevision": {
            "minimum": 1,
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "milestoneId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Milestoneid"
          },
          "priority": {
            "$ref": "#/components/schemas/TaskPriority"
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
          "expectedRevision",
          "stageId",
          "expectedProjectRevision"
        ],
        "type": "object"
      },
      {
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
          "assigneeUserId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Assigneeuserid"
          },
          "description": {
            "anyOf": [
              {
                "maxLength": 10000,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Description"
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
          "expectedProjectRevision": {
            "minimum": 1,
            "type": "integer"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "milestoneId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Milestoneid"
          },
          "priority": {
            "$ref": "#/components/schemas/TaskPriority"
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
          "expectedRevision",
          "milestoneId",
          "expectedProjectRevision"
        ],
        "type": "object"
      },
      {
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
          "assigneeUserId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Assigneeuserid"
          },
          "description": {
            "anyOf": [
              {
                "maxLength": 10000,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Description"
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
          "expectedProjectRevision": {
            "anyOf": [
              {
                "minimum": 1,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Expectedprojectrevision"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "milestoneId": false,
          "priority": {
            "$ref": "#/components/schemas/TaskPriority"
          },
          "stageId": false,
          "title": {
            "maxLength": 240,
            "minLength": 1,
            "title": "Title",
            "type": "string"
          }
        },
        "required": [
          "expectedRevision",
          "title"
        ],
        "type": "object"
      },
      {
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
          "assigneeUserId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Assigneeuserid"
          },
          "description": {
            "anyOf": [
              {
                "maxLength": 10000,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Description"
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
          "expectedProjectRevision": {
            "anyOf": [
              {
                "minimum": 1,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Expectedprojectrevision"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "milestoneId": false,
          "priority": {
            "$ref": "#/components/schemas/TaskPriority"
          },
          "stageId": false,
          "title": {
            "maxLength": 240,
            "minLength": 1,
            "title": "Title",
            "type": "string"
          }
        },
        "required": [
          "expectedRevision",
          "description"
        ],
        "type": "object"
      },
      {
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
          "assigneeUserId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Assigneeuserid"
          },
          "description": {
            "anyOf": [
              {
                "maxLength": 10000,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Description"
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
          "expectedProjectRevision": {
            "anyOf": [
              {
                "minimum": 1,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Expectedprojectrevision"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "milestoneId": false,
          "priority": {
            "$ref": "#/components/schemas/TaskPriority"
          },
          "stageId": false,
          "title": {
            "maxLength": 240,
            "minLength": 1,
            "title": "Title",
            "type": "string"
          }
        },
        "required": [
          "expectedRevision",
          "assigneeUserId"
        ],
        "type": "object"
      },
      {
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
          "assigneeUserId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Assigneeuserid"
          },
          "description": {
            "anyOf": [
              {
                "maxLength": 10000,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Description"
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
          "expectedProjectRevision": {
            "anyOf": [
              {
                "minimum": 1,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Expectedprojectrevision"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "milestoneId": false,
          "priority": {
            "$ref": "#/components/schemas/TaskPriority"
          },
          "stageId": false,
          "title": {
            "maxLength": 240,
            "minLength": 1,
            "title": "Title",
            "type": "string"
          }
        },
        "required": [
          "expectedRevision",
          "priority"
        ],
        "type": "object"
      },
      {
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
          "assigneeUserId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Assigneeuserid"
          },
          "description": {
            "anyOf": [
              {
                "maxLength": 10000,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Description"
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
          "expectedProjectRevision": {
            "anyOf": [
              {
                "minimum": 1,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Expectedprojectrevision"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "milestoneId": false,
          "priority": {
            "$ref": "#/components/schemas/TaskPriority"
          },
          "stageId": false,
          "title": {
            "maxLength": 240,
            "minLength": 1,
            "title": "Title",
            "type": "string"
          }
        },
        "required": [
          "expectedRevision",
          "dueAt"
        ],
        "type": "object"
      },
      {
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
          "assigneeUserId": {
            "anyOf": [
              {
                "format": "uuid",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Assigneeuserid"
          },
          "description": {
            "anyOf": [
              {
                "maxLength": 10000,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Description"
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
          "expectedProjectRevision": {
            "anyOf": [
              {
                "minimum": 1,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Expectedprojectrevision"
          },
          "expectedRevision": {
            "minimum": 1,
            "title": "Expectedrevision",
            "type": "integer"
          },
          "milestoneId": false,
          "priority": {
            "$ref": "#/components/schemas/TaskPriority"
          },
          "stageId": false,
          "title": {
            "maxLength": 240,
            "minLength": 1,
            "title": "Title",
            "type": "string"
          }
        },
        "required": [
          "expectedRevision",
          "acceptanceCriteria"
        ],
        "type": "object"
      }
    ],
    "title": "TaskUpdateRequest"
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
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Email"
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
  },
  "ZipSkillSource": {
    "additionalProperties": false,
    "properties": {
      "contentBase64": {
        "maxLength": 349528,
        "minLength": 1,
        "title": "Contentbase64",
        "type": "string"
      },
      "fileName": {
        "maxLength": 120,
        "minLength": 1,
        "title": "Filename",
        "type": "string"
      },
      "type": {
        "const": "zip",
        "title": "Type",
        "type": "string"
      }
    },
    "required": [
      "type",
      "fileName",
      "contentBase64"
    ],
    "title": "ZipSkillSource",
    "type": "object"
  }
} as const;
