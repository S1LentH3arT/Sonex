import assert from 'node:assert/strict';

import {authBannerSignature, shouldAppendAuthBanner} from '../src/App.js';
import type {AuthRuntimeState} from '../src/types.js';

const readyState: AuthRuntimeState = {
    ready: true,
    provider: 'deepseek',
    model: 'deepseek-v4-pro',
    auth_type: 'api_key',
    credential_source: 'auth.json',
};

const sameStateWithReason: AuthRuntimeState = {
    ...readyState,
    reason: 'transient detail',
};

const changedModel: AuthRuntimeState = {
    ...readyState,
    model: 'deepseek-v4-flash',
};

assert.equal(shouldAppendAuthBanner(null, readyState), true);
assert.equal(shouldAppendAuthBanner(authBannerSignature(readyState), sameStateWithReason), false);
assert.equal(shouldAppendAuthBanner(authBannerSignature(readyState), changedModel), true);
