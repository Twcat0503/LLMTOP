export function Icon({ name, size = 20 }: { name: 'logo' | 'overview' | 'services' | 'hosts' | 'pause' | 'play' | 'refresh' | 'search' | 'close'; size?: number }) {
  const paths = {
    logo: <><path d="m4 5 6 6-6 6M13 20h9" /></>,
    overview: <><path d="M4 13h3v7H4zM10 5h3v15h-3zM16 9h3v11h-3z" fill="currentColor" stroke="none" /></>,
    services: <><path d="m12 3 8 5v9l-8 5-8-5V8l8-5ZM4 8l8 5 8-5M12 13v9" /></>,
    hosts: <><rect x="4" y="3" width="16" height="8" rx="1" /><rect x="4" y="14" width="16" height="8" rx="1" /><path d="M7 7h.1M7 18h.1M16 7h2M16 18h2" /></>,
    pause: <><path d="M8 5v14M16 5v14" strokeWidth="3" /></>,
    play: <path d="m8 5 11 7-11 7V5Z" />,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 14-2l1 2M19 16a8 8 0 0 1-14 2l-1-2" /></>,
    search: <><circle cx="10" cy="10" r="6" /><path d="m15 15 5 5" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
