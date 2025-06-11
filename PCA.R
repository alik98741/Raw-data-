# Load the necessary libraries
library(readxl)
library(factoextra)
library(ggplot2)

# Load the data
root <- read_excel("C:/Users/Administrator/OneDrive/Desktop/Dr Shakeel Latest/root.xlsx")

# Assuming the column name for treatments is 'Treatments' in the 'root' dataframe
arsenic$Treatments <- factor(arsenic$Treatments, levels = c("GD562-CK", "GD562-AS", "GD911-CK", "GD911-AS"))

# Separate the Treatments column
treatments <- arsenic$Treatments
pca_data <- arsenic[, -which(names(arsenic) == "Treatments")]  # Exclude 'Treatments' for PCA analysis

# Perform PCA
pca_result <- prcomp(pca_data, center = TRUE, scale. = TRUE)

# Map specific shapes to treatments
treatment_shapes <- c("GD562-CK" = 21, "GD562-AS" = 22, "GD911-CK" = 23, "GD911-AS" = 24)

# Assign custom colors to treatments
treatment_colors <- c("GD562-CK" = "#00008B", "GD562-AS" = "#ffa83a", "GD911-CK" = "#dc4fff", "GD911-AS" = "red")

# Create the biplot using factoextra package
pca_plot <- fviz_pca_biplot(pca_result,
                            geom.ind = "point",         # Use points for individuals
                            pointsize = 3,              # Size of points
                            fill.ind = treatments,      # Color by treatments
                            col.ind = treatments,       # Also color points by treatments
                            shape.ind = treatment_shapes[as.character(treatments)],  # Assign custom shapes
                            palette = treatment_colors, # Use custom colors
                            addEllipses = TRUE,         # Add confidence ellipses
                            ellipse.type = "confidence",
                            legend.title = "Treatments",
                            repel = TRUE,               # Avoid overlapping labels
                            arrowsize = 0.7,            # Size of variable arrows
                            col.var = "black",  labelsize = 8,         # Set all arrows to black color
) +
  theme_minimal() +
  ggtitle("A. Arsenic concentration PCA") +
  xlab(paste0("PC1 (", round(pca_result$sdev[1]^2 / sum(pca_result$sdev^2) * 100, 1), "%)")) +
  ylab(paste0("PC2 (", round(pca_result$sdev[2]^2 / sum(pca_result$sdev^2) * 100, 1), "%)")) +
  theme(
    plot.title = element_text(size = 22, face = "bold"),
    axis.title.x = element_text(size = 20, face = "bold"),
    axis.title.y = element_text(size = 20, face = "bold"),
    axis.text.x = element_text(size = 18, face = "bold"),
    axis.text.y = element_text(size = 18, face = "bold"),
    legend.title = element_text(size = 20, face = "bold"),  # Set legend title size
    legend.text = element_text(size = 18, face = "bold")   # Set legend text (treatment) size
  )

# Save the plot as a TIFF file
ggsave(filename = "arsenic PCA1.tiff", plot = pca_plot, dpi = 600, width = 10, height = 8, units = "in")
