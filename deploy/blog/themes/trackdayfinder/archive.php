<?php
/**
 * Archive — category / tag / author / date listings. Reuses the index card
 * layout with a heading that says what's being filtered (the breadcrumb in
 * header.php already echoes the same title).
 */
if ( ! defined( 'ABSPATH' ) ) exit; get_header(); ?>

<div class="tdf-page" style="margin:0 0 18px">
	<h1 style="margin:0 0 6px"><?php the_archive_title(); ?></h1>
	<?php the_archive_description( '<p class="tdf-post-meta" style="text-transform:none;font-size:14px;letter-spacing:0">', '</p>' ); ?>
</div>

<?php if ( have_posts() ) : ?>

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
			<h2 style="margin-top:0">
				<a href="<?php the_permalink(); ?>" style="color:var(--fg)"><?php the_title(); ?></a>
			</h2>
			<?php the_excerpt(); ?>
			<a href="<?php the_permalink(); ?>" class="tdf-readmore">Read more &rarr;</a>
		</article>
	<?php endwhile; ?>

	<div class="tdf-pagination">
		<?php
		echo paginate_links( array(
			'prev_text' => '&larr; Newer',
			'next_text' => 'Older &rarr;',
		) );
		?>
	</div>

<?php else : ?>

	<article class="tdf-post">
		<h1>Nothing here yet.</h1>
		<p>No posts in this archive yet. <a href="<?php echo esc_url( home_url( '/' ) ); ?>">Back to the blog</a>.</p>
	</article>

<?php endif; ?>

<?php get_footer(); ?>
