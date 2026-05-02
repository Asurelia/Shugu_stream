import Head from "next/head";

type MetaProps = {
  /**
   * Override the default page title. When set, the document `<title>`
   * becomes `${title}` while the og/twitter `title` metas keep the
   * default site branding ("Shugu ♡ AI VTuber live") so SEO/social
   * cards stay consistent across sub-pages.
   */
  title?: string;
};

export const Meta = ({ title }: MetaProps = {}) => {
  const defaultTitle = "Shugu ♡ AI VTuber live";
  const documentTitle = title ?? defaultTitle;
  const description =
    "Une VTubeuse IA 3D en direct. Discute avec Shugu — elle parle, bouge, réagit. Multi-viewers en direct sur shugu.spoukie.uk ✨";
  return (
    <Head>
      <title>{documentTitle}</title>
      <meta name="description" content={description} />
      <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
      <meta property="og:title" content={defaultTitle} />
      <meta property="og:description" content={description} />
      <meta property="og:image" content="/shugu-og.png" />
      <meta property="og:type" content="website" />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={defaultTitle} />
      <meta name="twitter:description" content={description} />
      <meta name="twitter:image" content="/shugu-og.png" />
      <meta name="theme-color" content="#FF617F" />
    </Head>
  );
};
