import { describe, expect, it } from 'vitest'
import { inside, nearestPairs, resolveDrop } from './dnd.js'

const acts = [
  { type: 'defend', card: '10H', target: 0 },
  { type: 'defend', card: '10H', target: 1 },
  { type: 'transfer', card: '6S' },
  { type: 'defend', card: '6H', target: 1 },
  { type: 'take' },
]

describe('resolveDrop', () => {
  it('повертає карту в руку, якщо кинули не на стіл', () => {
    expect(resolveDrop(acts, '10H', { onTable: false, overPair: null })).toBeNull()
  })
  it('повертає карту, якщо для неї немає дій', () => {
    expect(resolveDrop(acts, 'KS', { onTable: true, overPair: null })).toBeNull()
  })
  it('відбиває саме ту карту, на яку кинули', () => {
    expect(resolveDrop(acts, '10H', { onTable: true, overPair: 1, nearest: [0, 1] }).target).toBe(1)
  })
  it('без точного влучання — найближча карта, яку можна побити', () => {
    expect(resolveDrop(acts, '6H', { onTable: true, overPair: null, nearest: [0, 1] }).target).toBe(1)
  })
  it('на вільне місце — перевід', () => {
    expect(resolveDrop(acts, '6S', { onTable: true, overPair: null, nearest: [0] }).type).toBe('transfer')
  })
  it('атака', () => {
    const a = [{ type: 'attack', card: '7C' }]
    expect(resolveDrop(a, '7C', { onTable: true, overPair: 0 })).toEqual(a[0])
  })
})

describe('geometry', () => {
  it('nearestPairs', () => {
    const r = (l) => ({ left: l, top: 0, width: 10, height: 10 })
    expect(nearestPairs([r(0), r(100), r(50)], 95, 5)).toEqual([1, 2, 0])
  })
  it('inside', () => {
    expect(inside({ left: 0, right: 10, top: 0, bottom: 10 }, 12, 5, 3)).toBe(true)
    expect(inside({ left: 0, right: 10, top: 0, bottom: 10 }, 15, 5, 3)).toBe(false)
  })
})
