export default function HomePage() {
  return (
    <>
      <title>Project Helios</title>
      <section className="home-page" aria-labelledby="home-title">
        <div className="home-heading">
          <h1 id="home-title">Project<br /><span>Helios.</span></h1>
        </div>
        <div className="helios-orbit" aria-hidden="true">
          <div className="orbit-ring orbit-ring-outer" />
          <div className="orbit-ring orbit-ring-inner" />
          <div className="orbit-core" />
        </div>
      </section>
    </>
  )
}
