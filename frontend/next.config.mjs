/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // We render graphics with a plain <img> (pixel-accurate overlay positioning),
  // so no next/image remote config is needed.
};

export default nextConfig;
