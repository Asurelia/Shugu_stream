import Head from "next/head";

export const Meta = () => {
  const title = "Shugu ♡ AI VTuber live";
  const description =
    "Une VTubeuse IA 3D en direct. Discute avec Shugu — elle parle, bouge, réagit. Multi-viewers en direct sur shugu.spoukie.uk ✨";
  return (
    <Head>
      <title>{title}</title>
      <meta name="description" content={description} />
      <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
      <meta property="og:title" content={title} />
      <meta property="og:description" content={description} />
      <meta property="og:image" content="/shugu-og.png" />
      <meta property="og:type" content="website" />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={title} />
      <meta name="twitter:description" content={description} />
      <meta name="twitter:image" content="/shugu-og.png" />
      <meta name="theme-color" content="#FF617F" />
    </Head>
  );
};
