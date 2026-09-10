import { describe, expect, it } from 'vitest'
import App from './App.vue'
import SecurityCenter from './SecurityCenter.vue'
import { resolveRootComponent } from './routeApp'

describe('resolveRootComponent', () => {
  it('keeps the netdisk app free of an SRC navigation entry', () => {
    expect(resolveRootComponent('/')).toBe(App)
    expect(resolveRootComponent('/files')).toBe(App)
  })

  it('routes only the dedicated SRC paths to Security Center', () => {
    expect(resolveRootComponent('/security')).toBe(SecurityCenter)
    expect(resolveRootComponent('/security/')).toBe(SecurityCenter)
    expect(resolveRootComponent('/admin/src')).toBe(SecurityCenter)
  })
})
