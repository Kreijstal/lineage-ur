#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <hardware/hwvulkan.h>
#include <vulkan/vk_android_native_buffer.h>

#define REQUIRE(expr) do { if (!(expr)) { fprintf(stderr, "failed: %s at %d\n", #expr, __LINE__); return 1; } } while (0)
#define VK_CHECK(expr) do { VkResult result = (expr); if (result != VK_SUCCESS) { fprintf(stderr, "%s returned %d at %d\n", #expr, result, __LINE__); return 1; } } while (0)
#define INSTANCE_FN(name) PFN_##name name = (PFN_##name)get(instance, #name); REQUIRE(name)
#define DEVICE_FN(name) PFN_##name name = (PFN_##name)vkGetDeviceProcAddr(device, #name); REQUIRE(name)

int main(int argc, char **argv) {
    REQUIRE(argc == 3 || argc == 4);
    int hal_required = argc == 3;
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    PFN_vkGetInstanceProcAddr get = (PFN_vkGetInstanceProcAddr)dlsym(library, "vk_icdGetInstanceProcAddr");
    REQUIRE(get);
    if (!hal_required) {
        typedef VkResult (VKAPI_PTR *Negotiate)(uint32_t *);
        Negotiate negotiate = (Negotiate)dlsym(library, "vk_icdNegotiateLoaderICDInterfaceVersion");
        REQUIRE(negotiate);
        uint32_t version = 5;
        VK_CHECK(negotiate(&version));
        REQUIRE(version >= 5);
    }
    hwvulkan_module_t *module = dlsym(library, "HMI");
    if (hal_required) {
        REQUIRE(module && module->common.tag == HARDWARE_MODULE_TAG);
        REQUIRE(strcmp(module->common.id, HWVULKAN_HARDWARE_MODULE_ID) == 0);
        hw_device_t *hw = NULL;
        REQUIRE(module->common.methods->open(&module->common, HWVULKAN_DEVICE_0, &hw) == 0);
        REQUIRE(hw && hw->tag == HARDWARE_DEVICE_TAG);
        hwvulkan_device_t *hal = (hwvulkan_device_t *)hw;
        REQUIRE(hal->GetInstanceProcAddr && hal->CreateInstance);
        get = hal->GetInstanceProcAddr;
    }
    VkInstance instance = VK_NULL_HANDLE;
    INSTANCE_FN(vkCreateInstance);
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName = "lineage-ur-check", .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo create = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
    VK_CHECK(vkCreateInstance(&create, NULL, &instance));
    INSTANCE_FN(vkDestroyInstance);
    INSTANCE_FN(vkEnumeratePhysicalDevices);
    INSTANCE_FN(vkGetPhysicalDeviceProperties);
    INSTANCE_FN(vkGetPhysicalDeviceQueueFamilyProperties);
    INSTANCE_FN(vkGetPhysicalDeviceMemoryProperties);
    INSTANCE_FN(vkEnumerateDeviceExtensionProperties);
    INSTANCE_FN(vkCreateDevice);
    INSTANCE_FN(vkGetDeviceProcAddr);
    uint32_t count = 1;
    VkPhysicalDevice physical;
    VK_CHECK(vkEnumeratePhysicalDevices(instance, &count, &physical));
    REQUIRE(count == 1);
    VkPhysicalDeviceProperties properties;
    vkGetPhysicalDeviceProperties(physical, &properties);
    REQUIRE(strstr(properties.deviceName, "SwiftShader"));
    printf("device: %s\n", properties.deviceName);
    count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, NULL);
    VkQueueFamilyProperties *families = calloc(count, sizeof(*families));
    REQUIRE(families);
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, families);
    uint32_t family;
    for (family = 0; family < count; ++family) if (families[family].queueFlags & VK_QUEUE_COMPUTE_BIT) break;
    REQUIRE(family < count);
    free(families);
    const char *ahb = "VK_ANDROID_external_memory_android_hardware_buffer";
    if (hal_required) {
        VK_CHECK(vkEnumerateDeviceExtensionProperties(physical, NULL, &count, NULL));
        VkExtensionProperties *extensions = calloc(count, sizeof(*extensions));
        REQUIRE(extensions);
        VK_CHECK(vkEnumerateDeviceExtensionProperties(physical, NULL, &count, extensions));
        int found = 0;
        for (uint32_t i = 0; i < count; ++i) if (!strcmp(extensions[i].extensionName, ahb)) found = 1;
        free(extensions);
        REQUIRE(found);
    }
    float priority = 1;
    VkDeviceQueueCreateInfo queue_info = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
    VkDeviceCreateInfo device_info = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &queue_info,
        .enabledExtensionCount = hal_required ? 1u : 0u, .ppEnabledExtensionNames = &ahb};
    VkDevice device;
    VK_CHECK(vkCreateDevice(physical, &device_info, NULL, &device));
    DEVICE_FN(vkDestroyDevice);
    DEVICE_FN(vkGetDeviceQueue);
    DEVICE_FN(vkCreateBuffer);
    DEVICE_FN(vkDestroyBuffer);
    DEVICE_FN(vkGetBufferMemoryRequirements);
    DEVICE_FN(vkAllocateMemory);
    DEVICE_FN(vkFreeMemory);
    DEVICE_FN(vkBindBufferMemory);
    DEVICE_FN(vkMapMemory);
    DEVICE_FN(vkUnmapMemory);
    DEVICE_FN(vkCreateShaderModule);
    DEVICE_FN(vkDestroyShaderModule);
    DEVICE_FN(vkCreateDescriptorSetLayout);
    DEVICE_FN(vkDestroyDescriptorSetLayout);
    DEVICE_FN(vkCreatePipelineLayout);
    DEVICE_FN(vkDestroyPipelineLayout);
    DEVICE_FN(vkCreateComputePipelines);
    DEVICE_FN(vkDestroyPipeline);
    DEVICE_FN(vkCreateDescriptorPool);
    DEVICE_FN(vkDestroyDescriptorPool);
    DEVICE_FN(vkAllocateDescriptorSets);
    DEVICE_FN(vkUpdateDescriptorSets);
    DEVICE_FN(vkCreateCommandPool);
    DEVICE_FN(vkDestroyCommandPool);
    DEVICE_FN(vkAllocateCommandBuffers);
    DEVICE_FN(vkBeginCommandBuffer);
    DEVICE_FN(vkEndCommandBuffer);
    DEVICE_FN(vkCmdBindPipeline);
    DEVICE_FN(vkCmdBindDescriptorSets);
    DEVICE_FN(vkCmdDispatch);
    DEVICE_FN(vkCmdPipelineBarrier);
    DEVICE_FN(vkQueueSubmit);
    DEVICE_FN(vkQueueWaitIdle);
    if (hal_required) {
        REQUIRE(vkGetDeviceProcAddr(device, "vkGetAndroidHardwareBufferPropertiesANDROID"));
        REQUIRE(vkGetDeviceProcAddr(device, "vkGetMemoryAndroidHardwareBufferANDROID"));
        PFN_vkGetSwapchainGrallocUsageANDROID gralloc = (PFN_vkGetSwapchainGrallocUsageANDROID)vkGetDeviceProcAddr(device, "vkGetSwapchainGrallocUsageANDROID");
        REQUIRE(gralloc);
        int usage = 0;
        VK_CHECK(gralloc(device, VK_FORMAT_R8G8B8A8_UNORM, VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT, &usage));
        REQUIRE(usage != 0);
    }
    VkBufferCreateInfo buffer_info = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = 256 * sizeof(uint32_t), .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
    VkBuffer buffer;
    VK_CHECK(vkCreateBuffer(device, &buffer_info, NULL, &buffer));
    VkMemoryRequirements requirements;
    vkGetBufferMemoryRequirements(device, buffer, &requirements);
    VkPhysicalDeviceMemoryProperties memory_properties;
    vkGetPhysicalDeviceMemoryProperties(physical, &memory_properties);
    uint32_t memory_type;
    for (memory_type = 0; memory_type < memory_properties.memoryTypeCount; ++memory_type) {
        VkMemoryPropertyFlags wanted = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        if ((requirements.memoryTypeBits & (1u << memory_type)) && (memory_properties.memoryTypes[memory_type].propertyFlags & wanted) == wanted) break;
    }
    REQUIRE(memory_type < memory_properties.memoryTypeCount);
    VkMemoryAllocateInfo memory_info = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = requirements.size, .memoryTypeIndex = memory_type};
    VkDeviceMemory memory;
    VK_CHECK(vkAllocateMemory(device, &memory_info, NULL, &memory));
    VK_CHECK(vkBindBufferMemory(device, buffer, memory, 0));
    uint32_t *values;
    VK_CHECK(vkMapMemory(device, memory, 0, requirements.size, 0, (void **)&values));
    memset(values, 0xcd, buffer_info.size);
    FILE *shader_file = fopen(argv[2], "rb");
    REQUIRE(shader_file && !fseek(shader_file, 0, SEEK_END));
    long shader_size = ftell(shader_file);
    REQUIRE(shader_size > 0 && shader_size % 4 == 0 && !fseek(shader_file, 0, SEEK_SET));
    uint32_t *code = malloc((size_t)shader_size);
    REQUIRE(code && fread(code, 1, (size_t)shader_size, shader_file) == (size_t)shader_size);
    fclose(shader_file);
    VkShaderModuleCreateInfo shader_info = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = (size_t)shader_size, .pCode = code};
    VkShaderModule shader;
    VK_CHECK(vkCreateShaderModule(device, &shader_info, NULL, &shader));
    free(code);
    VkDescriptorSetLayoutBinding binding = {.binding = 0, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .descriptorCount = 1, .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT};
    VkDescriptorSetLayoutCreateInfo set_info = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 1, .pBindings = &binding};
    VkDescriptorSetLayout set_layout;
    VK_CHECK(vkCreateDescriptorSetLayout(device, &set_info, NULL, &set_layout));
    VkPipelineLayoutCreateInfo layout_info = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &set_layout};
    VkPipelineLayout layout;
    VK_CHECK(vkCreatePipelineLayout(device, &layout_info, NULL, &layout));
    VkComputePipelineCreateInfo pipeline_info = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = layout,
        .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = shader, .pName = "main"}};
    VkPipeline pipeline;
    VK_CHECK(vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &pipeline_info, NULL, &pipeline));
    VkDescriptorPoolSize pool_size = {.type = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .descriptorCount = 1};
    VkDescriptorPoolCreateInfo pool_info = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &pool_size};
    VkDescriptorPool pool;
    VK_CHECK(vkCreateDescriptorPool(device, &pool_info, NULL, &pool));
    VkDescriptorSetAllocateInfo allocate_set = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = pool, .descriptorSetCount = 1, .pSetLayouts = &set_layout};
    VkDescriptorSet set;
    VK_CHECK(vkAllocateDescriptorSets(device, &allocate_set, &set));
    VkDescriptorBufferInfo descriptor_buffer = {.buffer = buffer, .range = buffer_info.size};
    VkWriteDescriptorSet write = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = set, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &descriptor_buffer};
    vkUpdateDescriptorSets(device, 1, &write, 0, NULL);
    VkCommandPoolCreateInfo command_pool_info = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = family};
    VkCommandPool command_pool;
    VK_CHECK(vkCreateCommandPool(device, &command_pool_info, NULL, &command_pool));
    VkCommandBufferAllocateInfo allocate_command = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = command_pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    VkCommandBuffer command;
    VK_CHECK(vkAllocateCommandBuffers(device, &allocate_command, &command));
    VkCommandBufferBeginInfo begin = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    VK_CHECK(vkBeginCommandBuffer(command, &begin));
    vkCmdBindPipeline(command, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    vkCmdBindDescriptorSets(command, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1, &set, 0, NULL);
    vkCmdDispatch(command, 32, 1, 1);
    VkMemoryBarrier barrier = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &barrier, 0, NULL, 0, NULL);
    VK_CHECK(vkEndCommandBuffer(command));
    VkQueue queue;
    vkGetDeviceQueue(device, family, 0, &queue);
    VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &command};
    VK_CHECK(vkQueueSubmit(queue, 1, &submit, VK_NULL_HANDLE));
    VK_CHECK(vkQueueWaitIdle(queue));
    for (uint32_t i = 0; i < 256; ++i) REQUIRE(values[i] == i * 7u + 3u);
    vkUnmapMemory(device, memory);
    vkDestroyCommandPool(device, command_pool, NULL);
    vkDestroyDescriptorPool(device, pool, NULL);
    vkDestroyPipeline(device, pipeline, NULL);
    vkDestroyPipelineLayout(device, layout, NULL);
    vkDestroyDescriptorSetLayout(device, set_layout, NULL);
    vkDestroyShaderModule(device, shader, NULL);
    vkDestroyBuffer(device, buffer, NULL);
    vkFreeMemory(device, memory, NULL);
    vkDestroyDevice(device, NULL);
    vkDestroyInstance(instance, NULL);
    puts(hal_required ? "PASS: Android HAL open, AHB entry points, gralloc usage, 256 JIT-computed values" : "PASS: standalone Bionic ICD, 256 JIT-computed values");
    return 0;
}
