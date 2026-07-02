import { existsSync, readFileSync, writeFileSync } from "node:fs";

const ROOT = new URL("..", import.meta.url);
const OUTPUT = new URL("docs/api/hermes-control-plane.openapi.yaml", ROOT);

const spec = `openapi: 3.1.0
info:
  title: Hermes Control Plane HTTP API
  version: 0.1.0
  summary: Convex HTTP routes for inbound messages and generated apps.
servers:
  - url: https://{deployment}.convex.site
    variables:
      deployment:
        default: example
paths:
  /sendblue/inbound/{token}:
    post:
      summary: Receive Sendblue inbound webhook events.
      operationId: receiveSendblueInbound
      parameters:
        - name: token
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/SendblueInbound"
      responses:
        "200":
          description: Event accepted, ignored, or deduplicated.
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/OkEnvelope"
        "401":
          description: Webhook token is missing or invalid.
  /telegram/inbound:
    post:
      summary: Receive Telegram bot webhook updates.
      operationId: receiveTelegramInbound
      parameters:
        - name: X-Telegram-Bot-Api-Secret-Token
          in: header
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              additionalProperties: true
      responses:
        "200":
          description: Update accepted or ignored.
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/OkEnvelope"
        "401":
          description: Secret token is missing or invalid.
  /app/{slug}:
    get:
      summary: Render a generated app shell.
      operationId: renderGeneratedApp
      parameters:
        - $ref: "#/components/parameters/Slug"
      responses:
        "200":
          description: HTML app shell.
          content:
            text/html:
              schema:
                type: string
        "404":
          description: App slug was not found.
  /app/{slug}/api/habits:
    get:
      summary: List habits for a generated app.
      operationId: listGeneratedAppHabits
      parameters:
        - $ref: "#/components/parameters/Slug"
      responses:
        "200":
          description: Current habits.
          content:
            application/json:
              schema:
                type: object
                required: [habits]
                properties:
                  habits:
                    type: array
                    items:
                      $ref: "#/components/schemas/Habit"
        "404":
          description: App slug was not found.
        "502":
          description: Data plane query failed.
    post:
      summary: Add a habit to a generated app.
      operationId: addGeneratedAppHabit
      parameters:
        - $ref: "#/components/parameters/Slug"
        - name: X-App-Write-Secret
          in: header
          required: false
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [title]
              properties:
                title:
                  type: string
                  minLength: 1
                  maxLength: 80
      responses:
        "201":
          description: Habit created.
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Habit"
        "400":
          description: Invalid request body.
        "401":
          description: Optional write secret did not match.
        "502":
          description: Data plane write failed.
  /app/{slug}/api/habits/{habitId}/check:
    post:
      summary: Mark a habit complete for today.
      operationId: checkGeneratedAppHabit
      parameters:
        - $ref: "#/components/parameters/Slug"
        - name: habitId
          in: path
          required: true
          schema:
            type: integer
            minimum: 1
      responses:
        "200":
          description: Habit check result.
          content:
            application/json:
              schema:
                type: object
                additionalProperties: true
        "400":
          description: Habit id is invalid.
        "404":
          description: Habit or app was not found.
        "502":
          description: Data plane write failed.
  /s/{handle}:
    get:
      summary: Serve a generated chat site.
      operationId: serveGeneratedSite
      parameters:
        - $ref: "#/components/parameters/Handle"
      responses:
        "200":
          description: Generated HTML site.
          content:
            text/html:
              schema:
                type: string
        "404":
          description: Site handle was not found.
  /site-data/{handle}:
    options:
      summary: CORS preflight for generated site data proxy.
      operationId: optionsSiteData
      parameters:
        - $ref: "#/components/parameters/Handle"
      responses:
        "200":
          description: CORS headers for the data proxy.
    post:
      summary: Run a guarded SQL statement for a generated site.
      operationId: runGeneratedSiteQuery
      parameters:
        - $ref: "#/components/parameters/Handle"
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [sql]
              properties:
                sql:
                  type: string
                args:
                  type: array
                  items: {}
      responses:
        "200":
          description: Turso result envelope.
          content:
            application/json:
              schema:
                type: object
                additionalProperties: true
        "400":
          description: SQL was rejected or data backend is unavailable.
        "404":
          description: Site handle was not found.
components:
  parameters:
    Slug:
      name: slug
      in: path
      required: true
      schema:
        type: string
        minLength: 1
    Handle:
      name: handle
      in: path
      required: true
      schema:
        type: string
        minLength: 1
  schemas:
    OkEnvelope:
      type: object
      additionalProperties: true
      properties:
        ok:
          type: boolean
        ignored:
          type: boolean
    SendblueInbound:
      type: object
      additionalProperties: true
      properties:
        content:
          type: string
        number:
          type: string
        message_handle:
          type: string
        media_url:
          type: string
        is_outbound:
          type: boolean
        opted_out:
          type: boolean
    Habit:
      type: object
      additionalProperties: true
      properties:
        id:
          type: integer
        title:
          type: string
        checkedToday:
          type: boolean
`;

const current = existsSync(OUTPUT) ? readFileSync(OUTPUT, "utf8") : "";

if (process.argv.includes("--check")) {
  if (current !== spec) {
    console.error("OpenAPI schema is stale. Run npm run docs:generate.");
    process.exit(1);
  }
  console.log("OpenAPI schema is current.");
} else {
  writeFileSync(OUTPUT, spec);
  console.log("Wrote docs/api/hermes-control-plane.openapi.yaml.");
}
