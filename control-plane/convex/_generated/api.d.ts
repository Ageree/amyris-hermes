/* eslint-disable */
/**
 * Generated `api` utility.
 *
 * THIS CODE IS AUTOMATICALLY GENERATED.
 *
 * To regenerate, run `npx convex dev`.
 * @module
 */

import type * as ResendOTP from "../ResendOTP.js";
import type * as admin from "../admin.js";
import type * as app_account from "../app/account.js";
import type * as app_authGate from "../app/authGate.js";
import type * as app_billing from "../app/billing.js";
import type * as app_channels from "../app/channels.js";
import type * as app_tiers from "../app/tiers.js";
import type * as app_upgrade from "../app/upgrade.js";
import type * as app_usage from "../app/usage.js";
import type * as auth from "../auth.js";
import type * as billing_grant from "../billing/grant.js";
import type * as billing_provider from "../billing/provider.js";
import type * as billing_stub from "../billing/stub.js";
import type * as billing_tiers from "../billing/tiers.js";
import type * as crons from "../crons.js";
import type * as fleet from "../fleet.js";
import type * as http from "../http.js";
import type * as intents from "../intents.js";
import type * as lib_auth from "../lib/auth.js";
import type * as lib_identity from "../lib/identity.js";
import type * as lib_sitelib from "../lib/sitelib.js";
import type * as lib_turso from "../lib/turso.js";
import type * as messages from "../messages.js";
import type * as migrations from "../migrations.js";
import type * as pairing from "../pairing.js";
import type * as quota from "../quota.js";
import type * as sites from "../sites.js";
import type * as testing from "../testing.js";

import type {
  ApiFromModules,
  FilterApi,
  FunctionReference,
} from "convex/server";

declare const fullApi: ApiFromModules<{
  ResendOTP: typeof ResendOTP;
  admin: typeof admin;
  "app/account": typeof app_account;
  "app/authGate": typeof app_authGate;
  "app/billing": typeof app_billing;
  "app/channels": typeof app_channels;
  "app/tiers": typeof app_tiers;
  "app/upgrade": typeof app_upgrade;
  "app/usage": typeof app_usage;
  auth: typeof auth;
  "billing/grant": typeof billing_grant;
  "billing/provider": typeof billing_provider;
  "billing/stub": typeof billing_stub;
  "billing/tiers": typeof billing_tiers;
  crons: typeof crons;
  fleet: typeof fleet;
  http: typeof http;
  intents: typeof intents;
  "lib/auth": typeof lib_auth;
  "lib/identity": typeof lib_identity;
  "lib/sitelib": typeof lib_sitelib;
  "lib/turso": typeof lib_turso;
  messages: typeof messages;
  migrations: typeof migrations;
  pairing: typeof pairing;
  quota: typeof quota;
  sites: typeof sites;
  testing: typeof testing;
}>;

/**
 * A utility for referencing Convex functions in your app's public API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = api.myModule.myFunction;
 * ```
 */
export declare const api: FilterApi<
  typeof fullApi,
  FunctionReference<any, "public">
>;

/**
 * A utility for referencing Convex functions in your app's internal API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = internal.myModule.myFunction;
 * ```
 */
export declare const internal: FilterApi<
  typeof fullApi,
  FunctionReference<any, "internal">
>;

export declare const components: {};
