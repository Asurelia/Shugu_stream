/**
 * Préfixe une URL relative avec le `basePath` de l'app.
 *
 * Historique : avant Next 16 cette fonction lisait `publicRuntimeConfig`
 * (runtime config). Next 16 ayant supprimé cette API, on lit désormais
 * `NEXT_PUBLIC_BASE_PATH` (build-time), inliné dans le bundle au build.
 * Pour changer le base path, rebuilder l'app avec la nouvelle valeur.
 *
 * Cas d'usage : déploiement github pages où l'app vit sous `/<repo>/`,
 * ou hosting derrière un reverse proxy avec un préfixe URL.
 */
export function buildUrl(path: string): string {
  const root = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  return root + path;
}
