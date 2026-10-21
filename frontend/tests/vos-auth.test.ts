import {test} from 'node:test'
import assert from 'node:assert/strict'
import {tokenFromAccessStore} from '../src/api/vos-auth.ts'
test('new and legacy VOS access stores preserve the actual user token', () => {
 for (const value of [
  {accessToken:'fixture-user-token'},
  {value:{accessToken:'fixture-user-token'}},
  {value:JSON.stringify({accessToken:'fixture-user-token'})},
  {value:{access_token:'fixture-user-token'}},
 ]) assert.equal(tokenFromAccessStore(JSON.stringify(value)), 'fixture-user-token')
 for (const value of [null, '', '{', '{}', '{"value":null}', '{"value":{"accessToken":{}}}']) assert.equal(tokenFromAccessStore(value), null)
})
