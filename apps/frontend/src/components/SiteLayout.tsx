import { useEffect, useRef } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'

const navigation = [
  { to: '/', label: 'Home' },
  { to: '/about', label: 'About' },
  { to: '/team', label: 'Meet the team' },
  { to: '/control', label: 'Control' },
]

export default function SiteLayout() {
  const { pathname } = useLocation()
  const previousPath = useRef(pathname)
  const mainRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (previousPath.current !== pathname) {
      window.scrollTo(0, 0)
      mainRef.current?.focus({ preventScroll: true })
      previousPath.current = pathname
    }
  }, [pathname])

  return (
    <div className="site-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="site-header">
        <div className="container header-inner">
          <Link className="wordmark" to="/" aria-label="Project Helios home">
            <span className="brand-symbol" aria-hidden="true" />
            Helios<span className="brand-period">.</span>
          </Link>
          <nav aria-label="Main navigation">
            {navigation.map(({ to, label }) => (
              <NavLink key={to} to={to} end>{label}</NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main id="main-content" className="container main-content" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="container footer-inner">
          <Link className="footer-brand" to="/">Project Helios</Link>
          <span>© {new Date().getFullYear()} Helios</span>
        </div>
      </footer>
    </div>
  )
}
