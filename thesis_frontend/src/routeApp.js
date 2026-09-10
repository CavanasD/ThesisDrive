import App from './App.vue'
import SecurityCenter from './SecurityCenter.vue'

export function resolveRootComponent(pathname = '/') {
  const normalized = pathname.replace(/\/+$/, '') || '/'
  return normalized === '/security' || normalized === '/admin/src'
    ? SecurityCenter
    : App
}
