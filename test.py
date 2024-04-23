from PIL import Image

def resize_and_center(input_path, output_path, new_size):
    # Open the image
    image = Image.open(input_path)
    
    # Resize the image while maintaining aspect ratio
    old_width, old_height = image.size
    ratio = max(new_size[0] / old_width, new_size[1] / old_height)
    new_width = int(old_width * ratio)
    new_height = int(old_height * ratio)
    resized_image = image.resize((new_width, new_height), Image.ANTIALIAS)
    
    # Create a new image with transparent background
    new_image = Image.new("RGBA", new_size, (255, 255, 255, 0))
    
    # Paste the resized image onto the new image, centered
    left = (new_size[0] - old_width) // 2
    top = (new_size[1] - old_height) // 2
    new_image.paste(image, (left, top))
    
    # Save the resulting image
    new_image.save(output_path)

def resize_and_center1(input_path, output_path, new_size):
    # Open the image
    image = Image.open(input_path)
    
    # Resize the image while maintaining aspect ratio
    old_width, old_height = image.size
    ratio = max(old_width/new_size[0], old_height/new_size[1])
    new_width = int(old_width * ratio)
    new_height = int(old_height * ratio)
    # resized_image = image.resize((new_width, new_height), Image.ANTIALIAS)
    
    # Create a new image with transparent background
    new_image = Image.new("RGBA", new_size, (255, 255, 255, 0))
    
    # Paste the resized image onto the new image, centered
    left = (new_size[0] - old_width) // 2
    top = (new_size[1] - old_height) // 2
    new_image.paste(image, (left, top))
    
    # Save the resulting image
    new_image.save(output_path)

def resize_image(input_image_path, output_image_path, size):
    original_image = Image.open(input_image_path)
    resized_image = original_image.resize(size)
    resized_image.save(output_image_path)

def add_padding(input_image_path, output_image_path, target_size):
    # Open the input image
    input_image = Image.open(input_image_path)

    # Create a new image with the target size and transparent background
    output_image = Image.new("RGBA", target_size, (0, 0, 0, 0))

    # Calculate the position to paste the input image
    x_offset = (target_size[0] - input_image.width) // 2
    y_offset = (target_size[1] - input_image.height) // 2

    # Paste the input image onto the output image with padding
    output_image.paste(input_image, (x_offset, y_offset))

    # Save the output image
    output_image.save(output_image_path)


def resize_and_crop(input_image_path, output_image_path, size):
    # Open the input image
    original_image = Image.open(input_image_path)

    # Calculate aspect ratios
    original_width, original_height = original_image.size
    target_width, target_height = size
    original_aspect_ratio = original_width / original_height
    target_aspect_ratio = target_width / target_height

    # Resize the image while preserving aspect ratio
    if original_aspect_ratio > target_aspect_ratio:
        # Fit image to target width
        new_width = target_width
        new_height = int(target_width / original_aspect_ratio)
    else:
        # Fit image to target height
        new_height = target_height
        new_width = int(target_height * original_aspect_ratio)

    resized_image = original_image.resize((new_width, new_height), Image.ANTIALIAS)

    # Calculate cropping box
    left = (new_width - target_width) / 2
    top = (new_height - target_height) / 2
    right = (new_width + target_width) / 2
    bottom = (new_height + target_height) / 2

    # Crop the image
    cropped_image = resized_image.crop((left, top, right, bottom))

    # Save the cropped image
    cropped_image.save(output_image_path)

def crop(input_image_path, output_image_path, size):
    # Open the input image
    original_image = Image.open(input_image_path)

    # Calculate aspect ratios
    original_width, original_height = original_image.size
    target_width, target_height = size
    original_aspect_ratio = original_width / original_height
    target_aspect_ratio = target_width / target_height

    # Resize the image while preserving aspect ratio
    if original_aspect_ratio > target_aspect_ratio:
        # Fit image to target width
        new_width = target_width
        new_height = int(target_width / original_aspect_ratio)
    else:
        # Fit image to target height
        new_height = target_height
        new_width = int(target_height * original_aspect_ratio)

    # resized_image = original_image.resize((new_width, new_height), Image.ANTIALIAS)

    # Calculate cropping box
    left = (new_width - target_width) / 2
    top = 0
    right = (new_width + target_width) / 2
    bottom = (new_height + target_height) / 2

    # Crop the image
    cropped_image = original_image.crop((left, top, right, bottom))

    # Save the cropped image
    cropped_image.save(output_image_path)


# Example usage
input_image_path = "input.png"
output_image_path = "output.png"
target_size = (1280, 800)
crop(input_image_path, output_image_path, target_size)


