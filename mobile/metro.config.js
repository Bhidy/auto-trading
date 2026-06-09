// Metro config — force a SINGLE three.js instance.
// Package-exports resolution can split `three` into ESM + CJS copies (R3F requires one,
// app code imports the other); two instances make the renderer silently draw nothing on native.
const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');

const config = getDefaultConfig(__dirname);

// Navigate from the CJS entry (safe to require.resolve) to the ESM module in the same dir.
const threeEntry = path.join(path.dirname(require.resolve('three')), 'three.module.js');

const baseResolveRequest = config.resolver.resolveRequest;
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (moduleName === 'three') {
    return { type: 'sourceFile', filePath: threeEntry };
  }
  return baseResolveRequest
    ? baseResolveRequest(context, moduleName, platform)
    : context.resolveRequest(context, moduleName, platform);
};

module.exports = config;
