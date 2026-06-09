import assert from 'node:assert/strict';

import { authBannerSignature, shouldAppendAuthBanner } from '../src/App.js';
import type { AuthRuntimeState } from '../src/types.js';

/**
 * Defines the ready state constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/static-banner.test.ts.
 */
const readyState: AuthRuntimeState = {
    ready: true,
    provider: 'deepseek',
    model: 'deepseek-v4-pro',
    auth_type: 'api_key',
    credential_source: 'auth.json',
};

/**
 * Defines the same state with reason constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/static-banner.test.ts.
 */
const sameStateWithReason: AuthRuntimeState = {
    ...readyState,
    reason: 'transient detail',
};

/**
 * Defines the changed model constant.
 *
 * Stores stable configuration or display data consumed by src/cli-ui/test/static-banner.test.ts.
 */
const changedModel: AuthRuntimeState = {
    ...readyState,
    model: 'deepseek-v4-flash',
};

assert.equal(shouldAppendAuthBanner(null, readyState), true);
assert.equal(shouldAppendAuthBanner(authBannerSignature(readyState), sameStateWithReason), false);
assert.equal(shouldAppendAuthBanner(authBannerSignature(readyState), changedModel), true);
