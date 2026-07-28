targetScope = 'subscription'

@minLength(1)
@maxLength(48)
@description('Name of the azd environment. Used to derive resource names.')
param environmentName string

@minLength(1)
@description('Azure region for the Foundry resource. Must support Foundry Agent Service.')
param location string

@description('Object ID of the user or service principal running the deployment. Granted Foundry User on the account.')
param principalId string = ''

@allowed(['User', 'ServicePrincipal'])
@description('Type of the principal in principalId. Use ServicePrincipal when deploying from CI.')
param principalType string = 'User'

@description('Model to deploy for the coordinator agent.')
param modelName string = 'gpt-5.4-mini'

@description('Version of the model to deploy. Leave empty to let Azure pick the default version.')
param modelVersion string = ''

@description('Tokens-per-minute capacity, in thousands, for the model deployment.')
@minValue(1)
param modelCapacity int = 20

@description('Name of the model deployment. The sample reads this as AZURE_AI_MODEL_DEPLOYMENT_NAME.')
param modelDeploymentName string = 'gpt-5.4-mini'

@description('Deployment SKU. Use DataZoneStandard or Standard if GlobalStandard quota is unavailable.')
param modelSkuName string = 'GlobalStandard'

var abbrs = {
  resourceGroup: 'rg-'
  foundryAccount: 'aif-'
}
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  sample: 'work-iq-a2a-foundry'
}

resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: '${abbrs.resourceGroup}${environmentName}'
  location: location
  tags: tags
}

module foundry 'foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    accountName: '${abbrs.foundryAccount}${resourceToken}'
    projectName: 'work-iq-a2a'
    location: location
    tags: tags
    principalId: principalId
    principalType: principalType
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
    modelDeploymentName: modelDeploymentName
    modelSkuName: modelSkuName
  }
}

@description('Foundry project endpoint. Read by the sample as AZURE_AI_PROJECT_ENDPOINT.')
output AZURE_AI_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint

@description('Model deployment name. Read by the sample as AZURE_AI_MODEL_DEPLOYMENT_NAME.')
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = foundry.outputs.modelDeploymentName

@description('Foundry account name, used by the post-provision script to create the A2A connection.')
output AZURE_AI_ACCOUNT_NAME string = foundry.outputs.accountName

@description('Foundry project name, used by the post-provision script to create the A2A connection.')
output AZURE_AI_PROJECT_NAME string = foundry.outputs.projectName

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location
