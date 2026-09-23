import { Link } from 'react-router'
import PageHeading from '../components/PageHeading'

export default function NotFoundPage() {
  return (
    <>
      <title>Page not found · Project Helios</title>
      <PageHeading title="Page not found" description="This page doesn't exist." />
      <Link className="text-link" to="/">Return home</Link>
    </>
  )
}
