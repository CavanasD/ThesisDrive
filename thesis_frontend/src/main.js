import { createApp } from 'vue'
import './style.css'
import { resolveRootComponent } from './routeApp'

createApp(resolveRootComponent(window.location.pathname)).mount('#app')
