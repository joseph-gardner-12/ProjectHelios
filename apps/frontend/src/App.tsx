import { BrowserRouter, Route, Routes } from 'react-router'
import SiteLayout from './components/SiteLayout'
import HomePage from './pages/HomePage'
import AboutPage from './pages/AboutPage'
import TeamPage from './pages/TeamPage'
import ControlPage from './pages/ControlPage'
import NotFoundPage from './pages/NotFoundPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<SiteLayout />}>
          <Route index element={<HomePage />} />
          <Route path="about" element={<AboutPage />} />
          <Route path="team" element={<TeamPage />} />
          <Route path="control" element={<ControlPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
