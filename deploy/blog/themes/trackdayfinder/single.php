<?php if ( ! defined( 'ABSPATH' ) ) exit; get_header(); ?>

<?php while ( have_posts() ) : the_post(); ?>
	<article class="tdf-post" id="post-<?php the_ID(); ?>">
		<p class="tdf-post-meta">
			<time datetime="<?php echo esc_attr( get_the_date( 'c' ) ); ?>"><?php echo esc_html( get_the_date() ); ?></time>
			<?php if ( get_the_author() ) : ?>
				&middot; by <?php the_author(); ?>
			<?php endif; ?>
			<?php $cats = get_the_category_list( ', ' ); if ( $cats ) : ?>
				&middot; <?php echo $cats; ?>
			<?php endif; ?>
		</p>
		<h1 style="margin-top:0"><?php the_title(); ?></h1>
		<?php if ( has_post_thumbnail() ) : ?>
			<div style="margin:0 0 18px">
				<?php the_post_thumbnail( 'large', array( 'style' => 'width:100%;height:auto;border-radius:6px;border:1px solid var(--line)' ) ); ?>
			</div>
		<?php endif; ?>

		<div class="tdf-content">
			<?php the_content(); ?>
			<?php wp_link_pages( array( 'before' => '<p>Pages: ', 'after' => '</p>' ) ); ?>
		</div>

		<?php $tags = get_the_tag_list( '', ' ' ); if ( $tags ) : ?>
			<p class="tdf-post-meta" style="margin-top:22px;text-transform:none;letter-spacing:0">Tags: <?php echo $tags; ?></p>
		<?php endif; ?>
	</article>

	<div style="display:flex;justify-content:space-between;gap:12px;margin-top:8px">
		<?php previous_post_link( '%link', '&larr; %title' ); ?>
		<?php next_post_link( '%link', '%title &rarr;' ); ?>
	</div>

	<?php if ( comments_open() || get_comments_number() ) : ?>
		<div class="tdf-page" style="margin-top:18px">
			<?php comments_template(); ?>
		</div>
	<?php endif; ?>

<?php endwhile; ?>

<?php get_footer(); ?>
