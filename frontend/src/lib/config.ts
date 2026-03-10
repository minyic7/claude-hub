export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '',
  wsUrl: import.meta.env.VITE_WS_URL || `ws://${window.location.host}/ws`,
  defaultTheme: (import.meta.env.VITE_DEFAULT_THEME || 'system') as 'light' | 'dark' | 'system',
}
