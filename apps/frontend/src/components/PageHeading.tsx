type PageHeadingProps = { title: string; description: string }

export default function PageHeading({ title, description }: PageHeadingProps) {
  return (
    <header className="page-heading">
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
  )
}
