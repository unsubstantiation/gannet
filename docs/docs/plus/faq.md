---
id: faq
title: FAQ
---

### Are my models trained just on my image uploads? How are they built?

Upstream Frigate+ models are built by fine tuning a base model with the images you have annotated and verified. The base model is trained from scratch from a sampling of images across all upstream Frigate+ user submissions and takes weeks of expensive GPU resources to train. If the models were built using your image uploads alone, you would need to provide tens of thousands of examples and it would take more than a week (and considerable cost) to train. Diversity helps the model generalize.

### Are my video feeds sent to the cloud for analysis when using upstream Frigate+ models?

No. Upstream Frigate+ models are a drop in replacement for the default model. All processing is performed locally as always. The only images sent to upstream Frigate+ are the ones you specifically submit via the `Send to upstream Frigate+` button or upload directly.

### Can I label anything I want and train the model to recognize something custom for me?

Not currently. At the moment, the set of labels will be consistent for all users. The focus will be on expanding that set of labels before working on completely custom user labels.

### Can upstream Frigate+ models be used offline?

Yes. Models and metadata are stored in the `model_cache` directory within the config folder. Gannet will only attempt to download a model if it does not exist in the cache. This means you can backup the directory and/or use it completely offline.

### Can I keep using my upstream Frigate+ models even if I do not renew my subscription?

Yes. Subscriptions to upstream Frigate+ provide access to the infrastructure used to train the models. Models you train during an active subscription remain licensed for your continued use even after your subscription ends — models already in your model cache will keep working indefinitely. An active subscription is required to train new models and download new versions.

### Can I use upstream Frigate+ models commercially?

A standard subscription covers use on camera systems you own or operate, including for your business. A shop, restaurant, warehouse, or office running upstream Frigate+ at its own locations (including multiple locations) is exactly the kind of use the subscription is for.
What the standard subscription does not cover is using upstream Frigate+ models to provide a product or service to others. If you're deploying models at your customers' sites, bundling them with hardware you sell, or running them as part of a hosted or managed service, even if your customers never receive the model files themselves, you'll need a commercial license.
Note that professional installers are fine under standard subscriptions when each customer holds their own upstream Frigate+ subscription. The commercial license is for cases where your license powers your customers' sites.

### Why can't I submit images to upstream Frigate+?

If you've configured your API key and the upstream Frigate+ Settings page in the UI shows that the key is active, you need to ensure that snapshots are enabled for the cameras you'd like to submit images for.

```yaml
snapshots:
  enabled: true
```
